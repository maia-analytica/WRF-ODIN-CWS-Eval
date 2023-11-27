# -*- coding: utf-8 -*-
"""
Created on Mon Nov 20 09:01:49 2023

@author: YANGC2
"""

from utils.DBops import DB
import datetime as dt
import time
import pandas as pd
import numpy as np 
import pickle
import yaml
import os
from dotenv import load_dotenv
load_dotenv()

def get_nowcast(current_date):
    # download the pickle
    source_file = current_date.strftime('%Y_%m_%d_%H') +".pkl"
    destination_file = os.path.join(os.getcwd(),source_file)
    datalake.download_pkl_from_blob(source_file, destination_file)
    print(f" -- {source_file} -- downloaded")
    # read in the pkl file
    with open(destination_file,'rb') as file:
        sim_history = pickle.load(file)
        tsv_history = pickle.load(file)
    ss_results = sim_history[-1]
    ss_inputs = tsv_history[-1]
    print(f"    |-- ss_results read: {ss_results.index.min()} to {ss_results.index.max()} ")
    return ss_results, ss_inputs

def dataframe_to_dict_list(df):
    # Reset the index to make the datetime a column
    df_reset = df.reset_index()

    # Rename the 'index' column to something more meaningful, like 'datetime'
    df_reset.rename(columns={'index': 'MeasurementTime'}, inplace=True)

    # Convert the DataFrame to a dictionary
    data_dict = df_reset.to_dict(orient='records')

    return data_dict

if __name__ == "__main__":
    db_yaml = "db.yaml"
    datalake = DB(db_yaml = db_yaml)
    current_date = dt.datetime(2023,1,1,7)
    ss_results, ss_inputs = get_nowcast(current_date)
    print(ss_results.head())
    ss_results_dict = dataframe_to_dict_list(ss_results)
    print(ss_results_dict[1])

