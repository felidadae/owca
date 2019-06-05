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
                stage("Build and push Tensorflow training Docker image") {
                    when {expression{return params.BUILD_IMAGES}}
                    steps {
                    withCredentials([file(credentialsId: 'kaggle.json', variable: 'KAGGLE_JSON')]) {
                        sh '''
                        IMAGE_NAME=${DOCKER_REPOSITORY_URL}/wca/tensorflow_train:${GIT_COMMIT}
                        IMAGE_DIR=${WORKSPACE}/workloads/tensorflow_train
                        cp -r dist ${IMAGE_DIR}
                        cp -f ${KAGGLE_JSON} ${IMAGE_DIR}/kaggle.json
                        docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                        docker push ${IMAGE_NAME}
                        '''
                    }
                    }
                }
                stage("Build and push Tensorflow inference Docker image") {
                    when {expression{return params.BUILD_IMAGES}}
                    steps {
                    withCredentials([file(credentialsId: 'kaggle.json', variable: 'KAGGLE_JSON')]) {
                        sh '''
                        IMAGE_NAME=${DOCKER_REPOSITORY_URL}/wca/tensorflow_inference:${GIT_COMMIT}
                        IMAGE_DIR=${WORKSPACE}/workloads/tensorflow_inference
                        cp -r dist ${IMAGE_DIR}
                        cp -f ${KAGGLE_JSON} ${IMAGE_DIR}/kaggle.json
                        docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                        docker push ${IMAGE_NAME}
                        '''
                    }
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
    }
}
