pipeline {
    agent any
    parameters {
      booleanParam defaultValue: true, description: 'Build workload images.', name: 'BUILD_IMAGES'
    }
    environment {
        DOCKER_REPOSITORY_URL = credentials('DOCKER_REPOSITORY_URL')
    }
    stages{
        stage("Flake8 formatting scan") {
            steps {
                sh '''
                  make venv flake8
                '''
            }
        }
        stage("Run unit tests suite") {
            steps {
                sh '''
                  make venv junit
                '''
            }
            post {
                always {
                    junit 'unit_results.xml'
                }
            }
        }
        stage("Build pex files") {
            steps {
                sh '''
                  make venv dist
                '''
                archiveArtifacts(artifacts: "dist/**")
            }
        }
        stage("Build and push Workload Collocation Agent Docker image") {
            steps {
                sh '''
                IMAGE_NAME=${DOCKER_REPOSITORY_URL}/wca:${GIT_COMMIT}
                IMAGE_DIR=${WORKSPACE}

                docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                docker push ${IMAGE_NAME}
                '''
            }
        }
        stage("Building Docker images and do tests in parallel") {
            parallel {
                stage("Using tester") {
                    steps {
                        sh '''
                        sudo bash -c "
                        export PYTHONPATH="$(pwd):$(pwd)/tests/tester"
                        dist/wca.pex -c $(pwd)/tests/tester/configs/tester_example.yaml \
                        -r tester:Tester -r tester:MetricCheck -r tester:FileCheck \
                        --log=debug --root
                        "
                    '''
                    }
                }
                stage("Build and push Tensorflow Benchmark Docker image") {
                    when {expression{return params.BUILD_IMAGES}}
                    steps {
                    sh '''
                    IMAGE_NAME=${DOCKER_REPOSITORY_URL}/wca/tensorflow_benchmark:${GIT_COMMIT}
                    IMAGE_DIR=${WORKSPACE}/workloads/tensorflow_benchmark
                    cp -r dist ${IMAGE_DIR}
                    docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                    docker push ${IMAGE_NAME}
                    '''
                    }
                }
                stage("Build and push Redis Docker image") {
                    when {expression{return params.BUILD_IMAGES}}
                    steps {
                    sh '''
                    IMAGE_NAME=${DOCKER_REPOSITORY_URL}/wca/redis:${GIT_COMMIT}
                    IMAGE_DIR=${WORKSPACE}/workloads/redis
                    cp -r dist ${IMAGE_DIR}
                    docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                    docker push ${IMAGE_NAME}
                    '''
                    }
                }
                stage("Build and push stress-ng Docker image") {
                    when {expression{return params.BUILD_IMAGES}}
                    steps {
                    sh '''
                    IMAGE_NAME=${DOCKER_REPOSITORY_URL}/wca/stress_ng:${GIT_COMMIT}
                    IMAGE_DIR=${WORKSPACE}/workloads/stress_ng
                    cp -r dist ${IMAGE_DIR}
                    docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                    docker push ${IMAGE_NAME}
                    '''
                    }
                }
                stage("Build and push rpc-perf Docker image") {
                    when {expression{return params.BUILD_IMAGES}}
                    steps {
                    sh '''
                    IMAGE_NAME=${DOCKER_REPOSITORY_URL}/wca/rpc_perf:${GIT_COMMIT}
                    IMAGE_DIR=${WORKSPACE}/workloads/rpc_perf
                    cp -r dist ${IMAGE_DIR}
                    docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                    docker push ${IMAGE_NAME}
                    '''
                    }
                }
                stage("Build and push Twemcache Docker image") {
                    when {expression{return params.BUILD_IMAGES}}
                    steps {
                    sh '''
                    IMAGE_NAME=${DOCKER_REPOSITORY_URL}/wca/twemcache:${GIT_COMMIT}
                    IMAGE_DIR=${WORKSPACE}/workloads/twemcache
                    cp -r dist ${IMAGE_DIR}
                    docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                    docker push ${IMAGE_NAME}
                    '''
                    }
                }
                stage("Build and push YCSB Docker image") {
                    when {expression{return params.BUILD_IMAGES}}
                    steps {
                    sh '''
                    IMAGE_NAME=${DOCKER_REPOSITORY_URL}/wca/ycsb:${GIT_COMMIT}
                    IMAGE_DIR=${WORKSPACE}/workloads/ycsb
                    cp -r dist ${IMAGE_DIR}
                    docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                    docker push ${IMAGE_NAME}
                    '''
                    }
                }
                stage("Build and push Cassandra Stress Docker image") {
                    when {expression{return params.BUILD_IMAGES}}
                    steps {
                    sh '''
                    IMAGE_NAME=${DOCKER_REPOSITORY_URL}/wca/cassandra_stress:${GIT_COMMIT}
                    IMAGE_DIR=${WORKSPACE}/workloads/cassandra_stress
                    cp -r dist ${IMAGE_DIR}
                    docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                    docker push ${IMAGE_NAME}
                    '''
                    }
                }
                stage("Build and push mutilate Docker image") {
                    when {expression{return params.BUILD_IMAGES}}
                    steps {
                    sh '''
                    IMAGE_NAME=${DOCKER_REPOSITORY_URL}/wca/mutilate:${GIT_COMMIT}
                    IMAGE_DIR=${WORKSPACE}/workloads/mutilate
                    cp -r dist ${IMAGE_DIR}
                    docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                    docker push ${IMAGE_NAME}
                    '''
                    }
                }
                stage("Build and push SpecJBB Docker image") {
                    when {expression{return params.BUILD_IMAGES}}
                    steps {
                        withCredentials([file(credentialsId: 'specjbb', variable: 'SPECJBB_TAR')]) {
                            sh '''
                            IMAGE_NAME=${DOCKER_REPOSITORY_URL}/wca/specjbb:${GIT_COMMIT}
                            IMAGE_DIR=${WORKSPACE}/workloads/specjbb
                            cp ${SPECJBB_TAR} ${IMAGE_DIR}
                            tar -xC ${IMAGE_DIR} -f ${IMAGE_DIR}/specjbb.tar.bz2
                            cp -r dist ${IMAGE_DIR}
                            docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                            docker push ${IMAGE_NAME}
                            '''
                        }
                    }
                    post {
                        always {
                            sh '''
                            rm -rf ${WORKSPACE}/workloads/specjbb/specjbb.tar.bz2 ${WORKSPACE}/workloads/specjbb/specjbb ${WORKSPACE}/workloads/specjbb/dist
                            '''
                        }
                    }
                }
            }
            post {
                always {
                    sh '''
                    rm -f kaggle.json
                    '''
                }
            }
        }
        stage('WCA E2E tests') {
			/* If commit message contains substring [e2e-skip] then this stage is omitted. */
            when {
                expression {
                    return if_perform_e2e()
                }
            }
            environment {
                /* For E2E tests. */
                PLAYBOOK = 'workloads/run_workloads.yaml'
                PROMETHEUS = 'http://100.64.176.12:9090'
                BUILD_COMMIT="${GIT_COMMIT}"
                EXTRA_ANSIBLE_PARAMS = " "
                LABELS="{additional_labels: {build_number: \"${BUILD_NUMBER}\", build_node_name: \"${NODE_NAME}\", build_commit: \"${GIT_COMMIT}\"}}"
                RUN_WORKLOADS_SLEEP_TIME = 300
                INVENTORY="tests/e2e/demo_scenarios/common/inventory.yaml"
                TAGS = "twemcache_mutilate,redis_rpc_perf,cassandra_stress,cassandra_ycsb,twemcache_rpc_perf,specjbb,stress_ng,tensorflow_benchmark_prediction,tensorflow_benchmark_train"
            }
            failFast true
            parallel {
                stage('WCA E2E for Kubernetes') {
                    agent { label 'kubernetes' }
                    environment {
                        KUBERNETES_HOST='100.64.176.34'
                        CRT_PATH = '/etc/kubernetes/ssl'
                        CONFIG = 'wca_config_kubernetes.yaml'
                        HOST_INVENTORY='tests/e2e/demo_scenarios/common/inventory-kubernetes.yaml'
                        CERT='true'
                    }
                    steps {
                        wca_and_workloads_check()
                    }
                    post {
                        always {
                            clean()
                        }
                    }
                }
                stage('WCA E2E for Mesos') {
                    agent { label 'mesos' }
                    environment {
                        MESOS_MASTER_HOST='100.64.176.23'
                        MESOS_AGENT='100.64.176.14'
                        CONFIG = 'wca_config_mesos.yaml'
                        HOST_INVENTORY='tests/e2e/demo_scenarios/common/inventory-mesos.yaml'
                        CERT='false'
                    }
                    steps {
                        wca_and_workloads_check()
                    }
                    post {
                        always {
                            clean()
                        }
                    }
                }
            }
        }
    }
}



/*----------------------------------------------------------------------------------------------------------*/
/* Helper function */
/*----------------------------------------------------------------------------------------------------------*/
def wca_and_workloads_check() {
    images_check()
    sh "make venv"
    sh "make wca_package"
    print('Reconfiguring wca...')
    copy_files("${WORKSPACE}/tests/e2e/demo_scenarios/common/${CONFIG}", "${WORKSPACE}/tests/e2e/demo_scenarios/common/wca_config.yml.tmp")
    replace_in_config(CERT)
    copy_files("${WORKSPACE}/tests/e2e/demo_scenarios/common/wca_config.yml.tmp", "/etc/wca/wca_config.yml", true)
    sh "sudo chown wca /etc/wca/wca_config.yml"
    copy_files("${WORKSPACE}/dist/wca.pex", "/usr/bin/wca.pex", true)
    copy_files("${WORKSPACE}/tests/e2e/demo_scenarios/common/wca.service", "/etc/systemd/system/wca.service", true)
    sh "sudo systemctl daemon-reload"
    start_wca()
    copy_files("${WORKSPACE}/${HOST_INVENTORY}", "${WORKSPACE}/${INVENTORY}")
    replace_commit()
    run_workloads("${EXTRA_ANSIBLE_PARAMS}", "${LABELS}")
    sleep RUN_WORKLOADS_SLEEP_TIME
    test_wca_metrics()
}

def images_check() {
    print('Check if docker images build for this PR')
    /* Checking only for rpc_perf */
    check_image = sh(script: 'curl ${DOCKER_REPOSITORY_URL}/v2/wca/rpc_perf/manifests/${BUILD_COMMIT} | jq .name', returnStdout: true).trim()
    if (check_image == 'null') {
        print('Docker images are not available!')
        sh "exit 1"
    }
}

def clean() {
    print('Cleaning: stopping WCA and workloads .')
    stop_wca()
    stop_workloads("${EXTRA_ANSIBLE_PARAMS}")
    junit 'unit_results.xml'
}

def copy_files(src, dst, sudo=false) {
    if(sudo){
        sh "sudo cp -r ${src} ${dst}"
    }
    else{
        sh "cp -r ${src} ${dst}"
    }
}


def replace_commit() {
        contentReplace(
            configs: [
                fileContentReplaceConfig(
                    configs: [
                        fileContentReplaceItemConfig( search: 'BUILD_COMMIT', replace: "${GIT_COMMIT}", matchCount: 0),
                    ],
                    fileEncoding: 'UTF-8',
                    filePath: "${WORKSPACE}/tests/e2e/demo_scenarios/common/inventory.yaml")])
}

def replace_in_config(cert='false') {
    if(cert == 'true') {
        contentReplace(
            configs: [
                fileContentReplaceConfig(
                    configs: [
                        fileContentReplaceItemConfig( search: 'BUILD_COMMIT', replace: "${GIT_COMMIT}", matchCount: 0),
                        fileContentReplaceItemConfig( search: 'BUILD_NUMBER', replace: "${BUILD_NUMBER}", matchCount: 0),
                        fileContentReplaceItemConfig( search: 'CRT_PATH', replace: "${CRT_PATH}", matchCount: 0)
                    ],
                    fileEncoding: 'UTF-8',
                    filePath: "${WORKSPACE}/tests/e2e/demo_scenarios/common/wca_config.yml.tmp")])
    }
    else {
        contentReplace(
            configs: [
                fileContentReplaceConfig(
                    configs: [
                        fileContentReplaceItemConfig( search: 'BUILD_COMMIT', replace: "${GIT_COMMIT}", matchCount: 0),
                        fileContentReplaceItemConfig( search: 'BUILD_NUMBER', replace: "${BUILD_NUMBER}", matchCount: 0)
                    ],
                    fileEncoding: 'UTF-8',
                    filePath: "${WORKSPACE}/tests/e2e/demo_scenarios/common/wca_config.yml.tmp")])
    }
}


def start_wca() {
    print('Starting wca...')
    sh "sudo systemctl restart wca"
    sleep 5
    sh "sudo systemctl status wca"
}

def stop_wca() {
    print('Stopping wca...')
    sh "sudo systemctl stop wca"
    print('Stopped wca.')
}

def run_workloads(extra_params, labels) {
    dir('workloads') {
        print('Starting workloads...')
        sh '''ansible-playbook ${extra_params} -i ${WORKSPACE}/tests/e2e/demo_scenarios/run_workloads/inventory.yaml -i ${WORKSPACE}/${INVENTORY} --tags=${TAGS} -e "${LABELS}" ${WORKSPACE}/${PLAYBOOK}'''
    }
}

def stop_workloads(extra_params) {
    print('Stopping all workloads...')
    sh "ansible-playbook  ${extra_params}  -i ${WORKSPACE}/${INVENTORY} --tags=clean_jobs ${WORKSPACE}/${PLAYBOOK}"
    sleep 5 
}

def remove_file(path) {
    sh "sudo rm -f ${path}"
}

def test_wca_metrics() {
    sh "PYTHONPATH=. pipenv run pytest ${WORKSPACE}/tests/e2e/test_wca_metrics.py::test_wca_metrics --junitxml=unit_results.xml --log-level=debug --log-cli-level=debug -v"
}
def if_perform_e2e() {
    /* Check whether in commit message there is [e2e-skip] substring: if so then skip e2e stage. */
    /* I'm not 100% sure if checking of parents count is needed: it may be possible that just to take original
       commit HEAD~1 is only needed.  */
    parents_count = sh(returnStdout: true, script: "git show -s --pretty=%p HEAD | wc -w").trim()
    print(parents_count)
    if (parents_count == "1") {
        result = sh(
            returnStdout: true,
            script: "git show HEAD | grep '\\[e2e-skip\\]' || true"
        ).trim().split("\n").last().trim()
        print(result)
        return result == ""
    } else {
        result = sh(
            returnStdout: true,
            script: "git show HEAD~1 | grep '\\[e2e-skip\\]' || true"
        ).trim().split("\n").last().trim()
        print(result)
        return result == ""
    }
}
