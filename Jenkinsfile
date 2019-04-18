pipeline {
    agent any
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
        stage("Building Docker images in parallel") {
            parallel {
                stage("Build and push Tensorflow Benchmark Docker image") {
                    steps {
                        sh '''
                        IMAGE_NAME=${DOCKER_REPOSITORY_URL}/owca/tensorflow_benchmark:${GIT_COMMIT}
                        IMAGE_DIR=${WORKSPACE}/workloads/tensorflow_benchmark
                        cp -r dist ${IMAGE_DIR}
                        docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                        docker push ${IMAGE_NAME}
                        '''
                    }
                }
                stage("Build and push Redis Docker image") {
                    steps {
                        sh '''
                        IMAGE_NAME=${DOCKER_REPOSITORY_URL}/owca/redis:${GIT_COMMIT}
                        IMAGE_DIR=${WORKSPACE}/workloads/redis
                        cp -r dist ${IMAGE_DIR}
                        docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                        docker push ${IMAGE_NAME}
                        '''
                    }
                }
                stage("Build and push stress-ng Docker image") {
                    steps {
                        sh '''
                        IMAGE_NAME=${DOCKER_REPOSITORY_URL}/owca/stress_ng:${GIT_COMMIT}
                        IMAGE_DIR=${WORKSPACE}/workloads/stress_ng
                        cp -r dist ${IMAGE_DIR}
                        docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                        docker push ${IMAGE_NAME}
                        '''
                    }
                }
                stage("Build and push rpc-perf Docker image") {
                    steps {
                        sh '''
                        IMAGE_NAME=${DOCKER_REPOSITORY_URL}/owca/rpc_perf:${GIT_COMMIT}
                        IMAGE_DIR=${WORKSPACE}/workloads/rpc_perf
                        cp -r dist ${IMAGE_DIR}
                        docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                        docker push ${IMAGE_NAME}
                        '''
                    }
                }
                stage("Build and push Twemcache Docker image") {
                    steps {
                        sh '''
                        IMAGE_NAME=${DOCKER_REPOSITORY_URL}/owca/twemcache:${GIT_COMMIT}
                        IMAGE_DIR=${WORKSPACE}/workloads/twemcache
                        cp -r dist ${IMAGE_DIR}
                        docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                        docker push ${IMAGE_NAME}
                        '''
                    }
                }
                stage("Build and push YCSB Docker image") {
                    steps {
                        sh '''
                        IMAGE_NAME=${DOCKER_REPOSITORY_URL}/owca/ycsb:${GIT_COMMIT}
                        IMAGE_DIR=${WORKSPACE}/workloads/ycsb
                        cp -r dist ${IMAGE_DIR}
                        docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                        docker push ${IMAGE_NAME}
                        '''
                    }
                }
                stage("Build and push Cassandra Stress Docker image") {
                    steps {
                        sh '''
                        IMAGE_NAME=${DOCKER_REPOSITORY_URL}/owca/cassandra_stress:${GIT_COMMIT}
                        IMAGE_DIR=${WORKSPACE}/workloads/cassandra_stress
                        cp -r dist ${IMAGE_DIR}
                        docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                        docker push ${IMAGE_NAME}
                        '''
                    }
                }
                stage("Build and push mutilate Docker image") {
                    steps {
                        sh '''
                        IMAGE_NAME=${DOCKER_REPOSITORY_URL}/owca/mutilate:${GIT_COMMIT}
                        IMAGE_DIR=${WORKSPACE}/workloads/mutilate
                        cp -r dist ${IMAGE_DIR}
                        docker build -t ${IMAGE_NAME} -f ${IMAGE_DIR}/Dockerfile ${IMAGE_DIR}
                        docker push ${IMAGE_NAME}
                        '''
                    }
                }
                stage("Build and push SpecJBB Docker image") {
                    steps {
                        withCredentials([file(credentialsId: 'specjbb', variable: 'SPECJBB_TAR')]) {
                            sh '''
                            IMAGE_NAME=${DOCKER_REPOSITORY_URL}/owca/specjbb:${GIT_COMMIT}
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
