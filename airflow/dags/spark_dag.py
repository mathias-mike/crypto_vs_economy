from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from VariableAvailSensor import VariableAvailSensor
from airflow.models import Variable

import lib.utils as utils
import lib.aws_handler as aws_handler
import lib.spark_handler as spark_handler

import json


def install_dependencies():
    _, emr, _ = aws_handler.get_boto_clients(utils.AWS_REGION, utils.config, emr_get=True)
    cluster_id = Variable.get(utils.CLUSTER_ID)

    step1_name = 'Upgrade numpy'
    args1 = ['python3', '-m', 'pip', 'install', 'numpy', '--upgrade']
    _ = spark_handler.run_cluster_commands(emr, cluster_id, step1_name, args1)


    step2_name = 'Install other required python packages'
    args2 = ['python3', '-m', 'pip', 'install', 'requests', 'pandas', 'pandas-datareader']
    _ = spark_handler.run_cluster_commands(emr, cluster_id, step2_name, args2)




def upload_assets_scritp_to_s3():
    s3 = aws_handler.get_s3_client(utils.AWS_REGION, utils.config)
    s3_path = 'scripts/'
    file_name = 'pull_assets_data.py'

    spark_handler.upload_file_to_s3(s3, utils.S3_BUCKET, s3_path, utils.SCRIPTS_PATH, file_name)




def upload_econs_script_to_s3(**kwargs):
    econs_last_run = Variable.get(utils.ECONS_SCRIPT_LAST_RUN, default_var=None)
    
    if econs_last_run != None:
        
        prev_task_run = datetime.fromisoformat(econs_last_run)
        current_dag_run_date = datetime.fromisoformat(kwargs['ds'])


        if prev_task_run < current_dag_run_date - timedelta(days=365):
            Variable.set(utils.ECONS_SCRIPT_DONE, True)
            raise AirflowSkipException(f"No updates yet from last fetch ({prev_task_run}).")
            

    s3 = aws_handler.get_s3_client(utils.AWS_REGION, utils.config)
    s3_path = 'scripts/'
    file_name = 'pull_econs_data.py'

    spark_handler.upload_file_to_s3(s3, utils.S3_BUCKET, s3_path, utils.SCRIPTS_PATH, file_name)

    Variable.set(utils.ECONS_SCRIPT_LAST_RUN, current_dag_run_date)



def run_assets_script(**kwargs):
    _, emr, _ = aws_handler.get_boto_clients(utils.AWS_REGION, utils.config, emr_get=True)
    cluster_id = Variable.get(utils.CLUSTER_ID)
    step_name = "Pull assets data, transform and load to s3"
    file = 'scripts/' +  'pull_assets_data.py'
    script_location = 's3://' +  utils.S3_BUCKET + '/' + file

    aws_access_key_id = utils.config['AWS']['ACCESS_KEY_ID']
    aws_secret_access_key = utils.config['AWS']['SECRET_ACCESS_KEY']
    _12data_apikey = utils.config['TWELVE_DATA']['API_KEY']
    start_date = str(datetime.fromisoformat(kwargs['ds']) - timedelta(days=1))
    end_date = str(datetime.fromisoformat(kwargs['ds']))
    symbols = 'AAPL,TSLA,GOOGL,AMZN,BTC/USD,ETH/USD,BNB/USD,LTC/USD'
    companies = {
        "AAPL":"Apple Inc.",
        "TSLA":"Tesla, Inc.",
        "GOOGL":"Alphabet Inc.",
        "AMZN": "Amazon.com, Inc."
    }
    interval = "1h"
    output_bucket = 's3://' + utils.S3_BUCKET + '/'

    script_args = {}
    script_args['aws_access_key_id'] = aws_access_key_id
    script_args['aws_secret_access_key'] = aws_secret_access_key
    script_args['_12data_apikey'] = _12data_apikey
    script_args['start_date'] = start_date
    script_args['end_date'] = end_date
    script_args['symbols'] = symbols
    script_args['companies'] = companies
    script_args['interval'] = interval
    script_args['output_bucket'] = output_bucket
    script_args = json.dumps(script_args)
    

    args = ['spark-submit', script_location, script_args]
    _ = spark_handler.run_cluster_commands(emr, cluster_id, step_name, args)

    s3 = aws_handler.get_s3_client(utils.AWS_REGION, utils.config)
    spark_handler.delete_file_from_s3(s3, utils.S3_BUCKET, file)

    Variable.set(utils.ASSETS_SCRIPT_DONE, True)



def run_econs_script(**kwargs):
    _, emr, _ = aws_handler.get_boto_clients(utils.AWS_REGION, utils.config, emr_get=True)
    cluster_id = Variable.get(utils.CLUSTER_ID)
    step_name = "Pull econs data, transform and load to s3"
    file = 'scripts/' +  'pull_econs_data.py'
    script_location = 's3://' + utils.S3_BUCKET + '/' + file

    aws_access_key_id = utils.config['AWS']['ACCESS_KEY_ID']
    aws_secret_access_key = utils.config['AWS']['SECRET_ACCESS_KEY']
    indicators = [
        {
            "symbol":"SL.UEM.TOTL.NE.ZS",
            "indicator":"Unemployment, total (% of total labor force) (national estimate)"
        },
        {
            "symbol":"NY.GDP.MKTP.CD",
            "indicator":"GDP (current US$)"
        },
        {
            "symbol":"PA.NUS.FCRF",
            "indicator":"Official exchange rate (LCU per US$, period average)"
        },
        {
            "symbol":"FR.INR.RINR",
            "indicator":"Real interest rate (%)"
        },
        {
            "symbol":"SP.POP.TOTL",
            "indicator":"Population, total"
        }
    ]
    countries = ["US", "NG", "CA", "CN"]

    year = datetime.fromisoformat(kwargs['ds']).year - 1 # As data for current year might not be filled in yet
    start_year = year
    end_year = year
    output_bucket = 's3://' + utils.S3_BUCKET + '/'

    script_args = {}
    script_args['aws_access_key_id'] = aws_access_key_id
    script_args['aws_secret_access_key'] = aws_secret_access_key
    script_args['indicators'] = indicators
    script_args['countries'] = countries
    script_args['start_year'] = start_year
    script_args['end_year'] = end_year
    script_args['output_bucket'] = output_bucket
    script_args = json.dumps(script_args)

    args = ['spark-submit', script_location, script_args]
    _ = spark_handler.run_cluster_commands(emr, cluster_id, step_name, args)

    s3 = aws_handler.get_s3_client(utils.AWS_REGION, utils.config)
    spark_handler.delete_file_from_s3(s3, utils.S3_BUCKET, file)


    Variable.set(utils.ECONS_SCRIPT_DONE, True)


def exit_from_dag():
    cluster_id = Variable.get(utils.CLUSTER_ID)

    Variable.delete(utils.CLUSTER_ID)
    Variable.delete(utils.ECONS_SCRIPT_DONE)
    Variable.delete(utils.ECONS_SCRIPT_DONE)

    Variable.set(utils.DELETE_CLUSTER, cluster_id)


default_args = {
    'owner': 'mike',
    'depends_on_past': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=5),
    'email_on_retry': False,
    'start_date': datetime(2016, 1, 1),
}


with DAG("spark_dag", 
            default_args=default_args,
            catchup=False,
            description='Pull assets and econs data and save in s3 data lake',
            schedule_interval='@daily') as dag:

    initializing_task = VariableAvailSensor(
        task_id="initializing",
        poke_interval=120,
        varnames=[utils.CLUSTER_ID],
        mode='reschedule'
    )


    install_dependencies_task = PythonOperator(
        task_id="install_dependencies",
        python_callable=install_dependencies
    )


    upload_assets_scritp_to_s3_task = PythonOperator(
        task_id="upload_assets_scritp_to_s3",
        python_callable=upload_assets_scritp_to_s3
    )


    upload_econs_script_to_s3_task = PythonOperator(
        task_id="upload_econs_script_to_s3",
        python_callable=upload_econs_script_to_s3,
        provide_context=True
    )


    run_assets_script_task = PythonOperator(
        task_id="run_assets_script_task",
        python_callable=run_assets_script,
        provide_context=True
    )


    run_econs_scripts_task = PythonOperator(
        task_id="run_econs_scripts_task",
        python_callable=run_econs_script,
        provide_context=True
    )


    wait_for_spark_complete_task = VariableAvailSensor(
        task_id="wait_for_spark_complete",
        poke_interval=120,
        timeout = 600,
        varnames=[utils.ASSETS_SCRIPT_DONE, utils.ECONS_SCRIPT_DONE],
        mode='reschedule'
    )

    finish_task = PythonOperator(
        task_id="finish_task",
        python_callable=exit_from_dag
    )


    initializing_task >> install_dependencies_task
    install_dependencies_task >> [upload_assets_scritp_to_s3_task, upload_econs_script_to_s3_task]
    upload_assets_scritp_to_s3_task >> run_assets_script_task
    upload_econs_script_to_s3_task >> run_econs_scripts_task

    wait_for_spark_complete_task >> finish_task




