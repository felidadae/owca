# Copyright (c) 2018 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""
Module is responsible for creating and initialization related software components
using yaml based configuration file.

It is a simple dependency injection framework that only take cares of initialization
phase of life cycle of objects (not full IoC container).

It is connected with 'components' module which plays a role of registry of all components.

One additionally feature is builtin support for including other yaml files
using special tag called !file (check _file_loader_constructor docs for detailed descriptor).
"""
import enum
import functools
import inspect
import io
import ipaddress
import logging
import types
import typing
from os.path import exists, isabs, split  # direct target import for mocking purposes in test_main
from ruamel import yaml
from typing import Any
from urllib.parse import urlparse

from wca import logger

_yaml = yaml.YAML(typ='safe')

log = logging.getLogger(__name__)

ROOT_PATH = ''

_registered_tags = set()


class ConfigLoadError(Exception):
    """Error raised for any of improper config file. """
    pass


class ValidationError(Exception):
    """Used for serious validation errors, that force program to stop. """


class WeakValidationError(ValidationError):
    """Used for weak validation errors, that handling depends on strict_mode setting.
    Such errors can be handled in following ways:
    - re-raise ValidationError exception
    - just print log.warning.
    """


def assure_base_types(value, base_types):
    for base_type in base_types:
        if isinstance(value, base_type):
            break
    else:
        raise ValidationError('Invalid type: {}. Type must be one of '
                              'the following: {}'.format(type(value),
                                                         base_types))


def assure_max_str_length(value, max_size):
    length = len(value)
    if length > max_size:
        raise ValidationError('Given str is too long. '
                              'Max allowed length is {}. '
                              'Got {}'.format(max_size, length))


def assure_max_numeric_value(value, max_value):
    if value > max_value:
        raise ValidationError(
            'Maximum value is {}. Got {}.'.format(max_value, value))


def assure_min_numeric_value(value, min_value):
    if value < min_value:
        raise ValidationError('Minimum value is {}. Got {}.'.format(
            min_value, value))


def assure_absolute_path(value):
    if not isabs(value):
        raise ValidationError('`absolute` option is set to True meaning '
                              'absolute path is obligatory. Use absolute '
                              'path or turn off `absolute` option by '
                              'setting it to False.')


def assure_no_parent_directory_access(value):
    split_value = split(value)
    while split_value[0] and split_value[1]:
        if '..' in split_value:
            raise ValidationError('You are trying to access parent '
                                  'directory by using \'..\' expression'
                                  ' which is not allowed. Try using '
                                  'absolute path instead.')
        split_value = split(split_value[0])


def assure_scheme_in_url(url, supported_schemes=('http', 'https')):
    if url.scheme not in supported_schemes:
        raise ValidationError('Invalid url. Got: {}. '
                              'Use one of supported schemes: '
                              '{}'.format(url.scheme, supported_schemes))


def assure_netloc_in_url(url):
    if not url.netloc:
        raise ValidationError('Invalid url. Netloc can\'t be empty.')


def assure_path_in_url(url):
    if not url.path:
        raise ValidationError('Invalid url. Path can\'t be empty when '
                              '`is_path_obligatory` is set to True.')


def assure_ip_format(ip):
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        raise ValidationError('Given str: \'{}\' '
                              'is not valid ip address'.format(ip))


def assure_port_format(port):
    try:
        int(port)
    except ValueError:
        raise ValidationError('Given str: \'{}\' '
                              'is not valid port value'.format(port))


class SemanticType:
    """Represents user input in different types."""


class _StrType(type):

    @classmethod
    def assure(cls, value):
        """Validates str input"""
        assure_base_types(value, [str])
        assure_max_str_length(value, cls.max_size)


def Str(max_size=400):
    return _StrType('Str', (_StrType, SemanticType), dict(max_size=max_size))


class _NumericType(type):

    @classmethod
    def assure(cls, value):
        """Validates numeric input"""
        assure_base_types(value, [int, float])
        assure_min_numeric_value(value, cls.min_value)
        assure_max_numeric_value(value, cls.max_value)


def Numeric(min_value, max_value):
    return _NumericType('Numeric', (_NumericType, SemanticType),
                        dict(min_value=min_value, max_value=max_value))


class _UrlType(type):

    @classmethod
    def assure(cls, value):
        """Validates url input"""
        assure_base_types(value, [str])
        assure_max_str_length(value, cls.max_size)

        url = urlparse(value)
        assure_scheme_in_url(url, supported_schemes=cls.supported_schemes)
        assure_netloc_in_url(url)
        if cls.is_path_obligatory:
            assure_path_in_url(url)


def Url(max_size=400, supported_schemes=('http', 'https'),
        is_path_obligatory=False):
    return _UrlType('Url', (_UrlType, SemanticType),
                    dict(max_size=max_size,
                         supported_schemes=supported_schemes,
                         is_path_obligatory=is_path_obligatory))


class _PathType(type):

    @classmethod
    def assure(cls, value):
        """Validates path input"""
        assure_base_types(value, [str])
        assure_max_str_length(value, cls.max_size)
        assure_no_parent_directory_access(value)
        if cls.absolute:
            assure_absolute_path(value)


def Path(absolute=False, max_size=400):
    return _PathType('Path', (_PathType, SemanticType),
                     dict(absolute=absolute, max_size=max_size))


class _IpPort(type):

    @classmethod
    def assure(cls, value):
        """Validates input in format ip:port; for example 127.0.0.1:1234"""
        assure_base_types(value, [str])
        assure_max_str_length(value, cls.max_size)

        value = value.rsplit(':')
        ip = value[0]
        port = value[1]
        assure_ip_format(ip)
        assure_port_format(port)


def IpPort(max_size=400):
    return _IpPort('IpPort', (_IpPort, SemanticType),
                   dict(max_size=max_size))


def _assure_list_type(value: list, expected_type):
    """Validate that value is type of list and recursively matches expected List type."""
    if not isinstance(value, list):
        raise ValidationError('expected list-like type %r, but got %r', expected_type,
                              type(value))
    else:
        expected_item_type = expected_type.__args__[0]
        for idx, item in enumerate(value):
            # Recursion to inspect list elements.
            try:
                assure_type(item, expected_item_type)
            except ValidationError as e:
                raise ValidationError('invalid item in list at index %s: %s' % (idx, e)) \
                    from e


def _assure_dict_type(value: dict, expected_type):
    """Validate that value is type of dict and recursively matches expected Dict type."""
    if not isinstance(value, dict):
        raise ValidationError('expected dict-like type %r, but got %r' % (expected_type,
                              type(value)))
    else:
        expected_key_type, expected_value_type = expected_type.__args__
        for key, item_value in value.items():
            try:
                assure_type(key, expected_key_type)
            except ValidationError as e:
                raise ValidationError('Invalid key=%r in dict: %s' % (key, e)) from e
            try:
                assure_type(item_value, expected_value_type)
            except ValidationError as e:
                raise ValidationError(
                    'invalid value %r in in dict at key %s: %s' % (
                        item_value, key, e)) from e


def _assure_union_type(value, expected_type):
    """Validate that value is type of Union and recursively matches expected Union type."""
    exceptions_raised = []
    for union_expected_type in expected_type.__args__:
        try:
            assure_type(value, union_expected_type)
        except ValidationError as e:
            exceptions_raised.append(e)
            continue
        break
    else:
        # Value doesn't match any type from union.
        raise ValidationError(
            'improper type from union (got=%r expected=%r)! (suberrors=%s)' %
            (type(value), expected_type, exceptions_raised))


def _assure_enum_type(value, expected_type):
    """Validate that value according available values of enum."""

    assert isinstance(expected_type, enum.Enum.__class__)
    allowed_enum_instances = expected_type.__members__.values()

    # Check according enum instances.
    if value in allowed_enum_instances:
        return

    # Check according enum values.
    allowed_enum_values = [i.value for i in allowed_enum_instances]
    if value in allowed_enum_values:
        return

    # Value doesn't equal any value from Enum type.
    raise ValidationError(
        'improper value from enum kind (got=%r allowed=%r)!' % (value, allowed_enum_values))


def assure_type(value, expected_type):
    """Should raise ValidationError based exception if value is not an instance of expected_type.
    """
    if expected_type == inspect.Parameter.empty:
        raise WeakValidationError('missing type declaration!')

    if isinstance(expected_type, typing.GenericMeta):
        if issubclass(expected_type, typing.List):
            _assure_list_type(value, expected_type)
            return

        elif issubclass(expected_type, typing.Dict):
            _assure_dict_type(value, expected_type)
            return

        else:
            # Warn about generic unhandled types (e.g. Iterable[int]), because:
            # "Parameterized generics cannot be used with class or instance checks" limitation.
            raise WeakValidationError('generic type found %r' % expected_type)

    # Handle union type.
    if isinstance(expected_type, typing.Union.__class__):
        _assure_union_type(value, expected_type)
        return

    # Handle union type.
    if isinstance(expected_type, enum.Enum.__class__):
        _assure_enum_type(value, expected_type)
        return

    # Handle Semantic type.
    if isinstance(expected_type, types.FunctionType):
        expected_type = expected_type()

    if issubclass(expected_type, SemanticType):
        expected_type.assure(value)
        return

    # Handle simple types.
    if not isinstance(value, expected_type):
        raise ValidationError(
            'improper type (got=%r expected=%r)!' % (type(value), expected_type))


def _constructor(loader: yaml.loader.Loader, node: yaml.nodes.Node, cls: type, strict_mode: bool):
    """Create instance of registered class ('cls" from closure) in recursive manner.
    First create "blank" uninitialized instance, then validate provided data,
    and then when whole hierarchy was processed initialize them in reverse order.
    Creation happens from top.
    Initialization happens from bottom.

    To split creation from initialization we relay on internal ruamel implementation
    that uses generators to allow lazy object initialization. If constructor is generator
    (contain 'yield' keyword) constructor will be called by next() at least twice (if deep=False)
    or many times until exhaustion (deep=True)).
    Our own constructor is just really thin wrapper over default "construct_mapping" and we
    use "generator lazy initialization" feature - to use created mapping
    as arguments for cls.__init__.
    """
    # Create "blank" uninitialized instance of cls.
    instance = object.__new__(cls)

    log.log(logger.TRACE, 'construct %s', cls.__name__)

    # Replace all scalar nodes to "simple" mappings without value
    # in order to allow create empty instances.
    # TODO: consider using first flat parameter as "args"
    if isinstance(node, yaml.ScalarNode):
        if node.value is not None and node.value != '':
            log.warning('Value %r for class %r ignored!' % (node.value, cls.__name__))
        arguments = {}
    else:
        # construct_mapping: deep is used to first create underlying objects, deep=True is
        # always used for mapping type.
        arguments = loader.construct_mapping(node, deep=True)

    # Constructor arguments simple type validation.
    # Use annotated constructor (arguments type annotations) to validate provided arguments.
    signature = inspect.signature(cls.__init__)
    for name, parameter in signature.parameters.items():
        if name == 'self':
            continue

        assert parameter.kind in (
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ), 'YAML constructor only supports named ' \
           'keyword arguments got parameter %r(%r) for %r' % (parameter, parameter.kind, cls)

        expected_type = parameter.annotation

        # Only validate provided values (ignore defaults).
        if name in arguments:
            value = arguments[name]
            try:
                assure_type(value, expected_type)
            except WeakValidationError as e:
                msg = 'Invalid value %r%s for field %r in class %r: %s' % (
                    value, node.start_mark, name, cls.__name__, e)
                if strict_mode:
                    raise ConfigLoadError(msg) from e
                else:
                    log.warning(msg)

            except ValidationError as e:
                raise ConfigLoadError(
                    'Invalid value %r%s for field %r in class %r: %s' % (
                        value, node.start_mark, name, cls.__name__, e)) from e

    # End the creation step.
    yield instance

    # Continue with initialization.
    log.log(logger.TRACE, 'constructed object init %s(id=0x%x) with state=%r ',
            cls.__name__, id(instance), arguments)
    try:
        instance.__init__(**arguments)
    except TypeError as e:
        raise ConfigLoadError(
            'Cannot instantiate %r%s with arguments=%r (constructor signature is: %s)' % (
                cls.__name__, node.start_mark, arguments, signature)) from e
    except Exception as e:
        raise ConfigLoadError(
            'Cannot instantiate %r%s with arguments=%r'
            '(unexpected error=%s! run --log=debug for details)' % (
                cls.__name__, node.start_mark, arguments, e)) from e

    log.log(logger.TRACE, '%s(0x%x)=%r', cls.__name__, id(instance), vars(instance))


def register(cls=None, strict_mode: bool = True):
    """Register constructor from yaml for a given class.
    The class can be then initialized during yaml processing if appropriate tag is found.

    E.g. if we have Foo class then you can use '!Foo' in yaml file.

        foo: !Foo
            x: 1

    after processing this file with "load_config", we get:

        {
            "foo": <Foo: instance...>
        }

    To initialize the class, constructor will simply call __init__, with
    already preprocessed body of deeper yaml nodes. In above example:

        foo = Foo.__new__(Foo)  # construct uninitialized (blank) instance of given class
        foo.__init__(x=1) # initialize instance


    Can be used as function or decorator.

    @register  # with default strict_mode enabled
    class Foo: pass

    @register(strict_mode=False)
    class Foo: pass

    register(Foo, strict_mode=False)
    """

    def _register(cls):
        # Just simply register new constructor for given cls.
        log.log(logger.TRACE, 'registered class %r' % (cls.__name__))
        _yaml.constructor.add_constructor(
            '!%s' % cls.__name__, functools.partial(_constructor, cls=cls, strict_mode=strict_mode))
        _registered_tags.add(cls.__name__)
        return cls

    # See if we're being called as @dataclass or @dataclass().
    if cls is None:
        # We're called with parens with decorator parameters e.g. strict_mode
        return _register

    # We're called as without parens.
    return _register(cls)


def _parse(yaml_body: io.StringIO) -> Any:
    """Parses configuration from given yaml body and returns initialized object."""
    try:
        return _yaml.load(yaml_body)
    except yaml.constructor.ConstructorError as e:
        raise ConfigLoadError(
            '%s %s. ' % (e.problem, e.problem_mark) +
            'Available tags are: %s' % (', '.join(_registered_tags))
        ) from e


def load_config(filename: str) -> Any:
    """Reads config from base file (which can contain nested config file).

    :param filename: The base config file
    :returns deserialized objects from yaml
    """
    if not exists(filename):
        raise ConfigLoadError('Cannot find configuration file: %r' % filename)
    with open(filename) as f:
        return _parse(f)
