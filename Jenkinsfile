// Weekday night run of the production chain. The GRU is a research model: it is rerun by hand only.
pipeline {
    agent any
    options {
        timestamps()
        disableConcurrentBuilds()
        timeout(time: 90, unit: 'MINUTES')
    }
    triggers { cron('H 23 * * 1-5') }
    parameters {
        booleanParam(name: 'INGEST', defaultValue: true, description: 'Download fresh data; off reruns on the latest raw files')
    }
    environment {
        FRED_API_KEY = credentials('fred-api-key')
        POSTGRES_PASSWORD = credentials('postgres-password')
        MLFLOW_DISABLE_AGENT_HINT = '1'
    }
    stages {
        stage('Lint') {
            steps { script { env.STAGE_REACHED = env.STAGE_NAME }; sh 'ruff check .' }
        }
        stage('Tests') {
            steps { script { env.STAGE_REACHED = env.STAGE_NAME }; sh 'pytest -q' }
        }
        stage('Ingest') {
            when { expression { params.INGEST != false } }
            steps { script { env.STAGE_REACHED = env.STAGE_NAME }; sh 'python -m pipeline.ingest' }
        }
        stage('Quality gate') {
            steps { script { env.STAGE_REACHED = env.STAGE_NAME }; sh 'python -m pipeline.quality --fail-on critical' }
        }
        stage('Transform') {
            steps { script { env.STAGE_REACHED = env.STAGE_NAME }; sh 'python -m pipeline.transform' }
        }
        stage('Book') {
            steps { script { env.STAGE_REACHED = env.STAGE_NAME }; sh 'python -m pipeline.book' }
        }
        stage('Volatility') {
            steps {
                script { env.STAGE_REACHED = env.STAGE_NAME }
                sh 'python -m pipeline.vol_models --models ewma garch gjr har har_range xgboost'
            }
        }
        stage('VaR') {
            steps { script { env.STAGE_REACHED = env.STAGE_NAME }; sh 'python -m pipeline.var && python -m pipeline.backtest' }
        }
        stage('Volumes and costs') {
            steps { script { env.STAGE_REACHED = env.STAGE_NAME }; sh 'python -m pipeline.volume_models && python -m pipeline.costs' }
        }
        stage('Regimes') {
            steps { script { env.STAGE_REACHED = env.STAGE_NAME }; sh 'python -m pipeline.regimes' }
        }
        stage('Anomaly detector') {
            steps { script { env.STAGE_REACHED = env.STAGE_NAME }; sh 'python -m pipeline.anomaly_evaluation' }
        }
        stage('Publish') {
            steps { script { env.STAGE_REACHED = env.STAGE_NAME }; sh 'python -m pipeline.publish' }
        }
    }
    post {
        always {
            // Double quotes: Groovy fills ${...} only inside them.
            sh "python -m pipeline.monitor --job nightly --status ${currentBuild.currentResult} --started-ms ${currentBuild.startTimeInMillis} --stage '${env.STAGE_REACHED}'"
        }
    }
}
