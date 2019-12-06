pipeline {
    agent any
    parameters {
      booleanParam defaultValue: true, description: 'Run all pre-checks.', name: 'PRECHECKS'
      booleanParam defaultValue: true, description: 'Build WCA image.', name: 'BUILD_WCA_IMAGE'
      booleanParam defaultValue: true, description: 'Build wrappers and workload images.', name: 'BUILD_IMAGES'
      booleanParam defaultValue: true, description: 'E2E for Mesos.', name: 'E2E_MESOS'
      booleanParam defaultValue: true, description: 'E2E for Kubernetes.', name: 'E2E_K8S'
      booleanParam defaultValue: true, description: 'E2E for Kubernetes as Daemonset.', name: 'E2E_K8S_DS'
      string defaultValue: '121', description: 'Sleep time for E2E tests', name: 'SLEEP_TIME'
    }
    environment {
        DOCKER_REPOSITORY_URL = '100.64.176.12:80'
    }
    stages{
        stage("Flake8 formatting scan") {
            when {expression{return params.PRECHECKS}}
            steps {
                sh '''
                  make venv flake8
                '''
            }
        }
        stage("Run unit tests suite") {
            when {expression{return params.PRECHECKS}}
            steps {
                sh '''
                  make junit
                '''
            }
            post {
                always {
                    junit 'unit_results.xml'
                }
            }
        }
        stage("Generate documentation") {
            when {expression{return params.PRECHECKS}}
            steps {
                sh '''
                  make generate_docs
                '''
            }
        }
        stage("Build WCA pex (in docker and images)") {
            when {expression{return params.BUILD_WCA_IMAGE}}
            steps {
                sh '''
                  echo GIT_COMMIT=${GIT_COMMIT}
                  export WCA_IMAGE=${DOCKER_REPOSITORY_URL}/wca
                  export WCA_TAG=${GIT_COMMIT}
                  make wca_package_in_docker
                  docker push $WCA_IMAGE:$WCA_TAG
                  # Just for completeness (not used later)
                  make wca_docker_devel
                '''
            }
        }
        stage("Build pex files") {
            when {expression{return params.BUILD_IMAGES}}
            steps {
                sh '''
                  # speed up pex wrapper build time
                  # requieres .pex-build already filled with requirments
                  #export ADDITIONAL_PEX_OPTIONS='--no-index --cache-ttl=604800'
                  make wrapper_package
                '''
                archiveArtifacts(artifacts: "dist/**")
            }
        }
        stage("Check code with bandit") {
            when {expression{return params.PRECHECKS}}
             steps {
             sh '''
               make bandit bandit_pex
             '''
             archiveArtifacts(artifacts: "wca-bandit.html, wca-pex-bandit.html")
           }
        }
        stage("Building Docker images and do tests in parallel") {
            parallel {
                 stage("Using tester") {
                     when {expression{return params.PRECHECKS}}
                     steps {
                     sh '''
			         make tester
                     '''
                     }
                 }
                // Redis
                stage("Build and push Redis Docker image") {
                    when {expression{return params.BUILD_IMAGES}}
                    steps {
                    sh '''
                    IMAGE_NAME=${DOCKER_REPOSITORY_URL}/wca/redis:${GIT_COMMIT}
                    IMAGE_DIR=${WORKSPACE}/examples/workloads/redis
                    docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                    docker push ${IMAGE_NAME}
                    '''
                    }
                }
                // memtire-benchmar
                stage("Build and push memtier_benchmark Docker image") {
                    when {expression{return params.BUILD_IMAGES}}
                    steps {
                    sh '''
                    IMAGE_NAME=${DOCKER_REPOSITORY_URL}/wca/memtier_benchmark:${GIT_COMMIT}
                    IMAGE_DIR=${WORKSPACE}/examples/workloads/memtier_benchmark
                    cp -r dist ${IMAGE_DIR}
                    docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                    docker push ${IMAGE_NAME}
                    '''
                    }
                }
                // rpc-perf
                stage("Build and push stress-ng Docker image") {
                    when {expression{return params.BUILD_IMAGES}}
                    steps {
                    sh '''
                    IMAGE_NAME=${DOCKER_REPOSITORY_URL}/wca/stress_ng:${GIT_COMMIT}
                    IMAGE_DIR=${WORKSPACE}/examples/workloads/stress_ng
                    cp -r dist ${IMAGE_DIR}
                    docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                    docker push ${IMAGE_NAME}
                    '''
                    }
                }
                // rpc-perf
                stage("Build and push rpc-perf Docker image") {
                    when {expression{return params.BUILD_IMAGES}}
                    steps {
                    sh '''
                    IMAGE_NAME=${DOCKER_REPOSITORY_URL}/wca/rpc_perf:${GIT_COMMIT}
                    IMAGE_DIR=${WORKSPACE}/examples/workloads/rpc_perf
                    cp -r dist ${IMAGE_DIR}
                    docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                    docker push ${IMAGE_NAME}
                    '''
                    }
                }
                // Twemcache
                stage("Build and push Twemcache Docker image") {
                    when {expression{return params.BUILD_IMAGES}}
                    steps {
                    sh '''
                    IMAGE_NAME=${DOCKER_REPOSITORY_URL}/wca/twemcache:${GIT_COMMIT}
                    IMAGE_DIR=${WORKSPACE}/examples/workloads/twemcache
                    cp -r dist ${IMAGE_DIR}
                    docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                    docker push ${IMAGE_NAME}
                    '''
                    }
                }
                // YCSB
                stage("Build and push YCSB Docker image") {
                    when {expression{return params.BUILD_IMAGES}}
                    steps {
                    sh '''
                    IMAGE_NAME=${DOCKER_REPOSITORY_URL}/wca/ycsb:${GIT_COMMIT}
                    IMAGE_DIR=${WORKSPACE}/examples/workloads/ycsb
                    cp -r dist ${IMAGE_DIR}
                    docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                    docker push ${IMAGE_NAME}
                    '''
                    }
                }
                // Stress
                stage("Build and push Cassandra Stress Docker image") {
                    when {expression{return params.BUILD_IMAGES}}
                    steps {
                    sh '''
                    IMAGE_NAME=${DOCKER_REPOSITORY_URL}/wca/cassandra_stress:${GIT_COMMIT}
                    IMAGE_DIR=${WORKSPACE}/examples/workloads/cassandra_stress
                    cp -r dist ${IMAGE_DIR}
                    docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                    docker push ${IMAGE_NAME}
                    '''
                    }
                }
                stage("Build and push Sysbench Docker image") {
                    when {expression{return params.BUILD_IMAGES}}
                    steps {
                    sh '''
                    IMAGE_NAME=${DOCKER_REPOSITORY_URL}/wca/sysbench:${GIT_COMMIT}
                    IMAGE_DIR=${WORKSPACE}/examples/workloads/sysbench
                    cp -r dist ${IMAGE_DIR}
                    docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                    docker push ${IMAGE_NAME}
                    '''
                    }
                }
                // SpecJBB
                stage("Build and push SpecJBB Docker image") {
                    when {expression{return params.BUILD_IMAGES}}
                    steps {
                        withCredentials([file(credentialsId: 'specjbb', variable: 'SPECJBB_TAR')]) {
                            sh '''
                            IMAGE_NAME=${DOCKER_REPOSITORY_URL}/wca/specjbb:${GIT_COMMIT}
                            IMAGE_DIR=${WORKSPACE}/examples/workloads/specjbb
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
                            rm -rf ${WORKSPACE}/examples/workloads/specjbb/specjbb.tar.bz2 ${WORKSPACE}/examples/workloads/specjbb/specjbb ${WORKSPACE}/examples/workloads/specjbb/dist
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
                PLAYBOOK = 'examples/workloads/run_workloads.yaml'
                PROMETHEUS = 'http://100.64.176.12:9090'
                BUILD_COMMIT="${GIT_COMMIT}"
                EXTRA_ANSIBLE_PARAMS = " "
                LABELS="{additional_labels: {build_number: \"${BUILD_NUMBER}\", build_node_name: \"${NODE_NAME}\", build_commit: \"${GIT_COMMIT}\"}}"
                RUN_WORKLOADS_SLEEP_TIME = "${params.SLEEP_TIME}"
                INVENTORY="tests/e2e/demo_scenarios/common/inventory.yaml"
                // JUST ONE WORKLOAD
                TAGS = "stress_ng"
                // ALL SET OF WORKLOADS
                // TAGS = "redis_rpc_perf,cassandra_stress,cassandra_ycsb,twemcache_rpc_perf,twemcache_mutilate,specjbb,stress_ng"
            }
            failFast false
            parallel {
                stage('WCA Daemonset E2E for Kubernetes') {
                    when {expression{return params.E2E_K8S_DS}}
                    agent { label 'Daemonset' }
                    environment {
                        PROMETHEUS = 'http://100.64.176.18:30900'
                        KUBERNETES_HOST='100.64.176.32'
                        KUBECONFIG="${HOME}/.kube/admin.conf"
                        KUSTOMIZATION_MONITORING='examples/kubernetes/monitoring/'
                        KUSTOMIZATION_WORKLOAD='examples/kubernetes/workloads/'
                    }
                    steps {
                        kustomize_wca_and_workloads_check()
                    }
                    post {
                        always {
                            print('Cleaning workloads and wca...')
                            sh "kubectl delete -k ${WORKSPACE}/${KUSTOMIZATION_WORKLOAD} --wait=false"
                            sh "kubectl delete -k ${WORKSPACE}/${KUSTOMIZATION_MONITORING} --wait=false"
                            junit 'unit_results.xml'
                        }
                    }
                }
                stage('WCA E2E for Kubernetes') {
                    when {expression{return params.E2E_K8S}}
                    agent { label 'kubernetes' }
                    environment {
                        KUBERNETES_HOST='100.64.176.17'
                        CRT_PATH = '/etc/kubernetes/ssl'
                        CONFIG = 'wca_config_kubernetes.yaml'
                        HOST_INVENTORY='tests/e2e/demo_scenarios/common/inventory-kubernetes.yaml'
                        CERT='true'
                        KUBECONFIG="${HOME}/admin.conf"
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
                    when {expression{return params.E2E_MESOS}}
                    agent { label 'mesos' }
                    environment {
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
    print('-wca_and_workloads_check-')
    sh "echo GIT_COMMIT=$GIT_COMMIT"
    images_check()
    sh "make venv"
    sh "make wca_package_in_docker_with_kafka"
    print('Reconfiguring wca...')
    copy_files("${WORKSPACE}/tests/e2e/demo_scenarios/common/${CONFIG}", "${WORKSPACE}/tests/e2e/demo_scenarios/common/wca_config.yml.tmp")
    replace_in_config(CERT)
    copy_files("${WORKSPACE}/tests/e2e/demo_scenarios/common/wca_config.yml.tmp", "/etc/wca/wca_config.yml", true)
    sh "sudo chown wca /etc/wca/wca_config.yml"
    copy_files("${WORKSPACE}/dist/wca.pex", "/usr/bin/wca.pex", true)
    copy_files("${WORKSPACE}/tests/e2e/demo_scenarios/common/wca.service", "/etc/systemd/system/wca.service", true)
    sh "sudo systemctl daemon-reload"
    print('Start wca...')
    start_wca()
    copy_files("${WORKSPACE}/${HOST_INVENTORY}", "${WORKSPACE}/${INVENTORY}")
    replace_commit()
    print('Run workloads...')
    run_workloads("${EXTRA_ANSIBLE_PARAMS}", "${LABELS}")
    print('Sleeping...')
    sleep RUN_WORKLOADS_SLEEP_TIME
    print('Test E2E metrics...')
    test_wca_metrics()
}

def kustomize_wca_and_workloads_check() {
    print('-kustomize_wca_and_workloads_check-')
    sh "echo GIT_COMMIT=$GIT_COMMIT"
    print('Configure wca and workloads...')
    kustomize_replace_commit()
    kustomize_add_labels("memcached-mutilate")
    kustomize_add_labels("redis-memtier")
    kustomize_add_labels("stress")
    kustomize_add_labels("sysbench-memory")

    print('Configure images...')
    kustomize_set_docker_image("memcached-mutilate", "mutilate")
    kustomize_set_docker_image("redis-memtier", "memtier_benchmark")
    kustomize_set_docker_image("stress", "stress_ng")
    kustomize_set_docker_image("sysbench-memory", "sysbench")


    print('Starting wca...')
    sh "kubectl apply -k ${WORKSPACE}/${KUSTOMIZATION_MONITORING}"

    print('Deploy workloads...')
    sh "kubectl apply -k ${WORKSPACE}/${KUSTOMIZATION_WORKLOAD}"

    print('Scale up workloads...')
    // JUST ONE WORKLOAD
    def list = ["stress-stream-small"]
    // FULL SET OF WORKLOADS
    //def list = ["stress-stream-small","redis-small","memtier-small","sysbench-memory-small"]
    for(item in list){
        sh "kubectl scale --replicas=1 statefulset $item"
    }

    print('Sleep while workloads are running...')
    sleep RUN_WORKLOADS_SLEEP_TIME
    print('Test kustomize metrics...')
    test_wca_metrics_kustomize()
}

def kustomize_set_docker_image(workload, workload_image) {
    file = "${WORKSPACE}/examples/kubernetes/workloads/${workload}/kustomization.yaml"
    testing_image = "\nimages:\n" +
    "  - name: ${workload_image}\n" +
    "    newName: ${DOCKER_REPOSITORY_URL}/wca/${workload_image}\n" +
    "    newTag: ${GIT_COMMIT}\n"
    sh "echo '${testing_image}' >> ${file}"
}

def kustomize_replace_commit() {
    contentReplace(
        configs: [
            fileContentReplaceConfig(
                configs: [
                    fileContentReplaceItemConfig( search: 'devel', replace: "${GIT_COMMIT}", matchCount: 0),
                ],
                fileEncoding: 'UTF-8',
                filePath: "${WORKSPACE}/examples/kubernetes/monitoring/wca/kustomization.yaml")])
}

def kustomize_add_labels(workload) {
    contentReplace(
        configs: [
            fileContentReplaceConfig(
                configs: [
                    fileContentReplaceItemConfig( search: 'commonLabels:', replace:
                    "commonLabels:\n" +
                        "  build_commit: '${GIT_COMMIT}'\n" +
                        "  build_number: '${BUILD_NUMBER}'\n" +
                        "  node_name: '${NODE_NAME}'\n" +
                        "  workload_name: '${workload}'\n" +
                        "  env_uniq_id: '32'\n",
                    matchCount: 0),
                ],
                fileEncoding: 'UTF-8',
                filePath: "${WORKSPACE}/examples/kubernetes/workloads/${workload}/kustomization.yaml")])
}

def test_wca_metrics_kustomize() {
    sh "make venv; PYTHONPATH=. pipenv run pytest ${WORKSPACE}/tests/e2e/test_wca_metrics.py::test_wca_metrics_kustomize --junitxml=unit_results.xml --log-level=debug --log-cli-level=debug -v"
}

def images_check() {
    print('Check if docker images build for this PR ${GIT_COMMIT}')
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
