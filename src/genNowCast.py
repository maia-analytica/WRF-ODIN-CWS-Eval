# -*- coding: utf-8 -*-
"""
Created on Mon Nov 20 09:01:49 2023
Updated on Mon Nov 26 09:01:49 2023

@author: YANGC2
@author: Keaton Lesnik

This script is used to pull 'first run' pickle files and insert into an evaluation database of a 'nowcast' database.
"""

from utils.DBops import DB
import datetime as dt
from datetime import timedelta
from datetime import datetime
import time
import pandas as pd
import numpy as np 
import pickle
import yaml
import os
import pytz
from dotenv import load_dotenv
from pymongo import MongoClient
import argparse

load_dotenv()

def get_nowcast(current_date):
    # download the pickle
    source_file = current_date.strftime('%Y_%m_%d_%H') + ".pkl"
    destination_file = os.path.join(os.getcwd(), source_file)
    datalake.download_pkl_from_blob(source_file, destination_file)
    print(f" -- {source_file} -- downloaded")

    # read in the pkl file
    with open(destination_file, 'rb') as file:
        sim_history = pickle.load(file)
        tsv_history = pickle.load(file)

    ss_results = sim_history[-1]
    ss_inputs = tsv_history[-1]

    # Ensure the index is a DateTimeIndex
    ss_results.index = pd.to_datetime(ss_results.index)

    # Define start and end times for filtering
    start_time = pd.Timestamp(current_date.year, current_date.month, current_date.day, 7) - timedelta(days=1)
    end_time = pd.Timestamp(current_date.year, current_date.month, current_date.day, 7)

    # Filter the DataFrame between start_time and end_time
    ss_results = ss_results[(ss_results.index >= start_time) & (ss_results.index <= end_time)]

    print(f" |-- ss_results filtered: {ss_results.index.min()} to {ss_results.index.max()} ")

    # Delete the .pkl file after use
    try:
        os.remove(destination_file)
        print(f" -- {source_file} -- deleted")
    except OSError as e:
        print(f"Error: {e.filename} - {e.strerror}")

    return ss_results, ss_inputs

def dataframe_to_series_dict(df):
    # Reset the index to make the datetime a column
    df_reset = df.reset_index()

    # Ensure 'MeasurementTime' is in the desired string format
    df_reset['index'] = df_reset['index'].dt.strftime('%Y-%m-%d %H:%M:%S')

    # Rename the 'index' column to 'MeasurementTime'
    df_reset.rename(columns={'index': 'MeasurementTime'}, inplace=True)

    # Convert the DataFrame to a dictionary
    data_series_dict = df_reset.to_dict(orient='list')

    return data_series_dict

def enrich_dicts(ss_results_dict, ss_inputs_dict, ss_version):
    # Current timestamp in UTC for 'inserted_at'
    utc_now = datetime.now(pytz.utc)
    inserted_at_str = utc_now.strftime('%Y-%m-%d %H:%M:%S')

    # Start date from ss_results_dict
    startdate_str = 'N/A'
    if 'MeasurementTime' in ss_results_dict and len(ss_results_dict['MeasurementTime']) > 0:
        startdate_str = ss_results_dict['MeasurementTime'][0]  # already a string

    # Enrich ss_results_dict
    ss_results_dict['datatype'] = 'ssresults_run1'
    ss_results_dict['ss_version'] = ss_version
    ss_results_dict['startdate'] = startdate_str
    ss_results_dict['inserted_at'] = inserted_at_str

    # Enrich ss_inputs_dict
    ss_inputs_dict['datatype'] = 'ssinputs_run1'
    ss_inputs_dict['ss_version'] = ss_version
    ss_inputs_dict['startdate'] = startdate_str
    ss_inputs_dict['inserted_at'] = inserted_at_str

    return ss_results_dict, ss_inputs_dict

def print_first_values_of_dict(my_dict):
    for key, value_list in my_dict.items():
        if value_list:  # Check if the list is not empty
            first_value = value_list[0]
            print(f"{key}: {first_value}")
        else:
            print(f"{key}: No values")

def insert_to_db(ss_results_dict, ss_inputs_dict, db_ssnow_results, db_ssnow_inputs):
    # Insert ss_results_dict into the 'eval_nowcast_out' collection
    insert_result = db_ssnow_results.insert_one(ss_results_dict)
    print(f"Inserted ss_results_dict with ID: {insert_result.inserted_id}")

    # Insert ss_inputs_dict into the 'eval_nowcast_in' collection
    insert_result = db_ssnow_inputs.insert_one(ss_inputs_dict)
    print(f"Inserted ss_inputs_dict with ID: {insert_result.inserted_id}")

if __name__ == "__main__":
    # Set up argument parser
    parser = argparse.ArgumentParser(description="Process weather nowcast data.")
    parser.add_argument("start_date", help="Start date in YYYY-MM-DD format", type=str)
    parser.add_argument("end_date", help="End date in YYYY-MM-DD format", type=str)
    
    # Parse arguments
    args = parser.parse_args()

    db_yaml = "src/dicts/db.yml"
    datalake = DB(db_yaml=db_yaml)
    
    # Parse the start and end dates
    start = pd.to_datetime(args.start_date)
    end = pd.to_datetime(args.end_date)

    # Generate date range
    date_range = pd.date_range(start, end)

    # MongoDB Client Setup
    DB_CLIENT = MongoClient(os.getenv("CWS_DATABASE_URL"))
    DB_OUT = DB_CLIENT.datalake
    db_ssnow_results = DB_OUT['eval_nowcast_out']
    db_ssnow_inputs = DB_OUT['eval_nowcast_in']

    # Loop through each date
    for current_date in date_range:
        current_date_time = current_date.replace(hour=7, minute=0, second=0, microsecond=0)
        ss_results, ss_inputs = get_nowcast(current_date_time)
        ss_results_dict = dataframe_to_series_dict(ss_results)
        ss_inputs_dict = dataframe_to_series_dict(ss_inputs)
        model_version = '231001'
        ss_results_dict_enriched, ss_inputs_dict_enriched = enrich_dicts(ss_results_dict, ss_inputs_dict, model_version)
        insert_to_db(ss_results_dict_enriched, ss_inputs_dict_enriched, db_ssnow_results, db_ssnow_inputs)

