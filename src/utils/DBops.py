import time
import datetime as dt
import pandas as pd
import pymongo
import os
import yaml
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient
from dotenv import load_dotenv
load_dotenv()
import numpy as np


class DB:
    def __init__(self, db_yaml):
        self.yaml_dict = self.load_yaml(db_yaml)
        self.in_uri = os.getenv("CWS_DATABASE_URL")
        self.out_uri = os.getenv("JACOBS_DATABASE_URL")
        self.blob_uri = os.getenv("JACOBS_STORAGE_URL")
        # uri
        self.in_client = pymongo.MongoClient(self.in_uri)
        self.out_client = pymongo.MongoClient(self.out_uri)
        self.blob = BlobServiceClient.from_connection_string(self.blob_uri)
        # Name of the Mongo compatible database
        self.in_db = self.in_client[self.yaml_dict["source_db"]["cosmos_database_name"]]
        self.out_db = self.out_client[self.yaml_dict["destination_db"]["cosmos_database_name"]]
        self.blob_xml = self.blob.get_container_client(self.yaml_dict['blob']['xml_container_name'])
        self.blob_pkl = self.blob.get_container_client(self.yaml_dict['blob']['pkl_container_name'])

    def upload_xml_to_blob(self, source_file, destination_file):  
        connection_string = self.blob_uri
        container_name = self.yaml_dict['blob']['xml_container_name']
        file_path = source_file
        
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        container_client = blob_service_client.get_container_client(container_name)
        with open(file_path, "rb") as file:
            blob_client = container_client.upload_blob(name=destination_file, data=file,overwrite= True)
        print("File uploaded successfully.")
        
    def download_xml_from_blob(self,source_file, destination_file):
        blob = self.blob_xml.get_blob_client(source_file)
        with open(destination_file, "wb") as my_blob:
            blob_data = blob.download_blob()
            blob_data.readinto(my_blob)

    def upload_pkl_to_blob(self, source_file, destination_file):  
        connection_string = self.blob_uri
        container_name = self.yaml_dict['blob']['pkl_container_name']
        file_path = source_file
        
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        container_client = blob_service_client.get_container_client(container_name)
        with open(file_path, "rb") as file:
            blob_client = container_client.upload_blob(name=destination_file, data=file,overwrite= True)
        print("File uploaded successfully.")
        
    def download_pkl_from_blob(self,source_file, destination_file):
        blob = self.blob_pkl.get_blob_client(source_file)
        with open(destination_file, "wb") as my_blob:
            blob_data = blob.download_blob()
            blob_data.readinto(my_blob)
            

    def load_yaml(self, db_yaml):
        with open(db_yaml, "r") as stream:  # open the file
            try:
                yaml_dict = yaml.safe_load(stream)  # using the stream, load the contents safely
            except yaml.YAMLError as exc:  # print the exception if error
                print(exc)
        return yaml_dict  # return the contents of the file


    def query_lims_tag_and_range(self, time_range, tags):
        a_filter = {"_ts":{"$gte":time_range[0], "$lte":time_range[1]},
                    "MeasurementTag":{"$in":tags}}
        dfl = pd.DataFrame()
        for a_lims in self.yaml_dict['source_db']['lims']:
            try:
                result = pd.DataFrame(self.in_db[a_lims].find(a_filter))
                dfl = pd.concat([dfl,result])
            except:
                continue
        # Processing the lims data --> This should be costomized with each site 
        try:
            dfl = dfl.sort_values(by='_ca', ascending=True)
        except:
            dfl = dfl.sort_values(by='_inserted_at', ascending=True)
        dfl = dfl.drop_duplicates(subset=["MeasurementDate",'MeasurementTag'], keep= 'last')
        dfl = dfl.sort_values(by='_ts', ascending=True)
        dfl = dfl[["MeasurementDate","MeasurementTag","MeasuredValue"]].copy()
        
        return dfl

    def query_scada_tag_and_range(self, time_range, tags):
        a_filter = {"_ts":{"$gte":time_range[0], "$lte":time_range[1]},
                    "MeasurementTag":{"$in":tags}}
        dfl = pd.DataFrame()
        for a_lims in self.yaml_dict['source_db']['scada']:
            try:
                result = pd.DataFrame(self.in_db[a_lims].find(a_filter))
                dfl = pd.concat([dfl,result])
            except:
                continue
        # Processing the scada data --> This should be costomized with each site 
        try:
            dfl = dfl.sort_values(by="_inserted_at", ascending=True)
        except:
            dfl = dfl.sort_values(by="_ca", ascending=True)
            
        dfl = dfl.drop_duplicates(subset=["MeasurementTime", 'MeasurementTag'], keep= 'last')
        dfl = dfl.sort_values(by='_ts', ascending=True)
        dfl = dfl[["MeasurementTime","MeasurementTag","MeasuredValue"]].copy()
        
        return dfl

    def insert_dfl_into_collection(self,collection,dfl):
        dfl['inserted_at'] = dt.datetime.now()
        print(f"----- inserted into {collection} ----- ")
        time1= time.time()
        self.out_db[collection].insert_many(dfl.to_dict("records"))
        time2= time.time()
        print(f"  |-- Time Spent: {time2-time1} seconds")
        
    def query_last_stats(self, current_ts, n=1):
        collection = self.out_db[self.yaml_dict['destination_db']['stats']]
        pipeline = [
            {"$match":{"end_ts":{"$lte": current_ts}}},
            {"$sort":{"inserted_at":1}},
            {
                "$group" :{
                "_id" : {"stats":"$stats","tag":"$tag","end_ts":"$end_ts"},
                "value" : {"$last" : "$value"}
                }
            },
         {
                "$project": {
                    "_id": 0,
                    "stats": "$_id.stats",
                    "tag": "$_id.tag",
                    "value":"$value",
                    "end_ts":"$_id.end_ts",
                    "count": 1,
                    "total": 1
                }
            }
        ]                         
             
        dfl = pd.DataFrame(collection.aggregate(pipeline))
        dfw = dfl.pivot_table(values = 'value', index='stats',columns = 'tag', dropna = False, aggfunc = "mean")
        return dfl,dfw

    def query_scada_last_ts(self):
        """Return the most recent date in the ss_results collection."""
        # Get the latest year of scada_YYYY collection 
        col_list = self.in_db.list_collection_names()
        col_list = [x for x in col_list if "scada_2" in x]
        col_list.sort()
        my_col = col_list[-1]
        recent_date = self.in_db[my_col].find().sort([('_ts', -1)]).limit(1)[0]['_ts']
        return recent_date
    
    def query_lims_earlier_time_of_two_tags_with_lastest_n_points(self, n, current_ts, tag1, tag2):
        collection = self.in_db[self.yaml_dict['source_db']['lims'][0]]
        pipeline1 = [
            {"$match": {
                "_ts": {"$lte": current_ts},
                "MeasurementTag": tag1
                }},
            {"$sort": {
                "_ts": pymongo.DESCENDING
            }},
            {"$limit": n}
        ]
        df1 = pd.DataFrame(collection.aggregate(pipeline1))

        pipeline2 = [
            {"$match": {
                "_ts": {"$lte": current_ts},
                "MeasurementTag": tag2
                }},
            {"$sort": {
                "_ts": pymongo.DESCENDING
            }},
            {"$limit": n}
        ]
        df2 = pd.DataFrame(collection.aggregate(pipeline2))
        
        a = df1.MeasurementDate,df2.MeasurementDate
        return min(a[0].min(),a[1].min())

    def query_lims_earlier_time_of_one_tags_with_lastest_n_points(self, n, current_ts, tag1):
        collection = self.in_db[self.yaml_dict['source_db']['lims'][0]]
        pipeline1 = [
            {"$match": {
                "_ts": {"$lte": current_ts},
                "MeasurementTag": tag1
                }},
            {"$sort": {
                "_ts": pymongo.DESCENDING
            }},
            {"$limit": n}
        ]
        df1 = pd.DataFrame(collection.aggregate(pipeline1))

        return df1

    def query_ss_frac_clean_lastest_n_points(self, n, current_ts, tag1):
        current_ts = current_ts.strftime('%Y-%m-%d %H:%M:%S')
        collection = self.out_db[self.yaml_dict["destination_db"]['ss_frac_clean']]
        # pipeline1 = [
        #     {"$match": {
        #         "local_time": {"$lte": current_ts},
        #         "tag": tag1,
        #         "quality": "good"
        #         }},
        #     {"$sort": {
        #         "local_time": pymongo.DESCENDING
        #     }},
        #     {"$sort": {
        #         "inserted_at": pymongo.DESCENDING
        #     }},
        #     {"$limit": n}
        # ]
        # df1 = pd.DataFrame(collection.aggregate(pipeline1))
        pipeline = [
            {"$match": {
                "local_time": {"$lte": current_ts},
                "tag": tag1
                }},
            {"$sort": {
                "local_time": pymongo.DESCENDING
            }}]
        results = collection.aggregate(pipeline)
        dfl = pd.DataFrame(results)
        dfl = dfl.drop(dfl[dfl['quality'].isin(['bad'])].index)
        dfl = dfl.drop_duplicates(['local_time','tag','quality'], keep = 'first')
        dfl = dfl.head(n).copy()
        return dfl

    def query_ss_lims_clean_lastest_n_points(self, n, current_ts, tag1):
        current_ts = current_ts.strftime('%Y-%m-%d %H:%M:%S')
        collection = self.out_db[self.yaml_dict["destination_db"]['ss_lims_clean']]
        # pipeline1 = [
        #     {"$match": {
        #         "local_time": {"$lte": current_ts},
        #         "tag": tag1
        #         }},
        #     {"$sort": {
        #         "local_time": pymongo.DESCENDING
        #     }},
        #     {"$limit": n}
        # ]
        # dfl = pd.DataFrame(collection.aggregate(pipeline1))
        pipeline = [
            {"$match": {
                "local_time": {"$lte": current_ts},
                "tag": tag1
                }},
            {"$sort": {
                "local_time": pymongo.DESCENDING
            }}]
        results = collection.aggregate(pipeline)
        dfl = pd.DataFrame(results)
        dfl = dfl.drop(dfl[dfl['quality'].isin(['bad'])].index)
        dfl = dfl.drop_duplicates(['local_time','tag','quality'], keep = 'first')
        dfl = dfl.head(n).copy()

        return dfl
    
    def query_ss_tag_and_range(self, collection, time_range, tags):
        time_range = [x.strftime('%Y-%m-%d %H:%M:%S') for x in time_range]
        a_filter = {"$and":[{"local_time":{"$gte":time_range[0],"$lte":time_range[1]}},
                            {'tag': {"$in":tags}}]}
        my_scada = self.out_db[collection]
        my_docs = my_scada.find(a_filter)
        raw = pd.DataFrame(list(my_docs))

        # Preprocess
        dfl = raw.copy()

        # Step 1. remove rows whose quality is bad
        if 'quality' in dfl.columns:
            dfl = dfl.drop(dfl[dfl['quality'] == "bad"].index)
            dfl = dfl.drop(dfl[dfl['quality'] == "Bad"].index)
        # Step 2. get the lastest inserted 
        dfl = dfl.sort_values(by='inserted_at', ascending=True)
        dfl = dfl.drop_duplicates(subset=["local_time", "tag"], keep= 'last')
        dfl = dfl.sort_values(by='ts', ascending=True)
        # Step 3. Pivot table 
        dfl['local_time']=pd.to_datetime(dfl['local_time'])
        dfw  = dfl.pivot_table(values = 'value',index='local_time',columns = 'tag')
        return raw,dfl,dfw

    def query_ss_results_tag_and_range(self, time_range, tags):
        collection = self.yaml_dict["destination_db"]['ss_results']
        time_range = [x.strftime('%Y-%m-%d %H:%M:%S') for x in time_range]
        a_filter = {"$and":[{"local_time":{"$gte":time_range[0],"$lte":time_range[1]}},
                            {'tag': {"$in":tags}}]}
        my_scada = self.out_db[collection]
        my_docs = my_scada.find(a_filter)
        raw = pd.DataFrame(list(my_docs))

        # Preprocess
        dfl = raw.copy()
        # Step 2. get the lastest inserted 
        dfl = dfl.sort_values(by='inserted_at', ascending=True)
        dfl = dfl.drop_duplicates(subset=["local_time", "tag"], keep= 'last')
        dfl = dfl.sort_values(by='ts', ascending=True)
        # Step 3. Pivot table 
        dfl['local_time']=pd.to_datetime(dfl['local_time'])
        dfw  = dfl.pivot_table(values = 'value',index='local_time',columns = 'tag')
        return raw,dfl,dfw

    def query_settings_tag_and_range(self, form, time_range, tags):
        if form == "autocal":        
            collection = self.yaml_dict["destination_db"]["form_autocal_settings"]
        elif form == "manual":        
            collection = self.yaml_dict["destination_db"]["form_manual_settings"]
        else:
            raise NameError("form can only be 'autocal' or 'manual'")
        time_range = [x.strftime('%Y-%m-%d %H:%M:%S') for x in time_range]
        a_filter = {"$and":[{"local_time":{"$gte":time_range[0],"$lt":time_range[1]}},
                            {'tag': {"$in":tags}}]}
        my_scada = self.out_db[collection]
        my_docs = my_scada.find(a_filter)
        raw = pd.DataFrame(list(my_docs))

        # Preprocess
        dfl = raw.copy()
        # Step 2. get the lastest inserted 
        dfl = dfl.sort_values(by='inserted_at', ascending=True)
        dfl = dfl.drop_duplicates(subset=["local_time", "tag"], keep= 'last')
        dfl = dfl.sort_values(by='ts', ascending=True)
        # Step 3. Pivot table 
        dfl['local_time']=pd.to_datetime(dfl['local_time'])
        dfw  = dfl.pivot_table(values = 'value',index='local_time',columns = 'tag')
        return raw,dfl,dfw
    
    def query_settings(self,current_ts,form):
        if form == "autocal":        
            collection = self.yaml_dict["destination_db"]["form_autocal_settings"]
        elif form == "manual":        
            collection = self.yaml_dict["destination_db"]["form_manual_settings"]
        else:
            raise NameError("form can only be 'autocal' or 'manual'")
        mycol = self.out_db[collection]
        result= mycol.aggregate(
            [{"$match":{"local_time":{"$lte": current_ts.strftime('%Y-%m-%d %H:%M:%S')}}},
             {"$sort":{"local_time":1}},
             {"$sort":{"inserted_at":1}},
             {"$group" :
                {"_id" : "$tag",
                 "value" : {"$last" : "$value"},
                 "local_time" : {"$last" : "$local_time"}
                 }}
            ])
        df = pd.DataFrame(result)
        return df

    def query_forecast_outputs_tag_and_range(self, time_range, tags):
        # time_range = [int(x.timestamp() * 1000) for x in time_range]
        time_range = [x.strftime('%Y-%m-%d %H:%M:%S') for x in time_range]
        collection = self.yaml_dict["source_db"]["forecast_outputs"]
        # a_filter = {"_ts.$date":{"$gte":time_range[0],"$lte":time_range[1]}}
        a_filter = {"$and":[{"MeasurementTime":{"$gte":time_range[0],"$lte":time_range[1]}},
                            {"SUMO_encode_name": {"$in":tags}}]}
        my_scada = self.in_db[collection] 
        my_docs = my_scada.find(a_filter)
        # raw = my_scada.aggregate(pipeline)
        # dfl = pd.DataFrame(results)
        raw = pd.DataFrame(list(my_docs))
        raw['MeasurementTime'] = pd.to_datetime(raw['MeasurementTime'])
        # Create a pivot table from the DataFrame
        dfw = raw.pivot_table(index='MeasurementTime', columns='SUMO_encode_name', values='value', aggfunc='last')
        return raw, dfw
        
        
        
        
        
        
if __name__ =="__main__":
    db_yaml = os.path.join(r"C:/Users/yangc2/OneDrive - Jacobs/HybridOptimizer/CWS_softsensor/configurations/dev/db.yaml")
    datalake = DB(db_yaml)
    # %% Test query_lims_tag_and_range 
    # tags = ['51','10','14','999','1002','61','63','4935','4937','4948']
    # tags = ['14','61','51']
    # tags = ['77','63','14','51','21','25','61','39','1007']
    # # tags = ['16','17','18']
    # time_range = [dt.datetime(2022,7,1),dt.datetime(2023,9,27)]
    # lims = datalake.query_lims_tag_and_range(time_range,tags)
    # lims_w  = lims.pivot_table(values = 'MeasuredValue', index='MeasurementDate',columns = 'MeasurementTag', dropna = False, aggfunc = "mean")
    # lims_w = lims_w.dropna(how = "any")
    # # lims_w['ratio'] = lims_w[tags[0]]/lims_w[tags[1]]
    # lims_w['ratio'] = (lims_w[tags[0]]*1.07 + lims_w[tags[1]]*1.51 +lims_w[tags[2]]*1.82)/lims_w[tags[3]]
    # stats = lims_w.describe()
    # Q1 = stats.loc["25%",'ratio']
    # Q3 = stats.loc["75%",'ratio']
    # IQR = Q3 - Q1
    # lb = Q1 - 1.5*IQR
    # ub = Q3 + 1.5*IQR
    # print(stats)
    # print(lb,ub)
    
    # %% Test query_scada_tag_and_range
    # tags = ["DMSCADA.410FIT1613PV.F_CV",
    #     "DMSCADA.410FIT1614PV.F_CV",
    #     "DMSCADA.410FIT1615PV.F_CV",
    #     "DMSCADA.410FIT1616PV.F_CV",
    #     "DMSCADA.410FIT1617PV.F_CV",
    #     "DMSCADA.410FIT1618PV.F_CV",
    #     "DMSCADA.410FIT1619PV.F_CV"]
    # tags = ["DM999FIT9120PV.F_CV"]
    # time_range = [dt.datetime(2023,8,20,7),dt.datetime(2023,8,24,7)]
    # date_list = pd.date_range(time_range[0],time_range[1],freq="15T")
    # scada = datalake.query_scada_tag_and_range(time_range,tags)
    # scada['MeasurementTime'] = pd.to_datetime(scada['MeasurementTime'])
    # scada_w = scada.pivot_table(values ='MeasuredValue', index='MeasurementTime',columns = 'MeasurementTag', dropna = False, aggfunc = "mean")
    # scada_w = scada_w.resample('15T').mean()
    # # #%% Test query_last_stats
    # current_ts = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # _ ,stats = datalake.query_last_stats(current_ts)
    
    # #%% query_scada_last_ts
    # recent_date = datalake.query_scada_last_ts()




    # # %% query_ss_tag_and_range
    # ss_collection = "ss_scada_clean"
    # tags = ['DMSCADA.120FI01_TOTAL_R.F_CV','DMSCADA.08FIT12101_FLOW.F_CV',"DMSCADA.410FIT1619PV.F_CV"]
    # tags = ['DMSCADA.MRP5101_SPD_FDBK.F_CV']
    # tags = ["DMSCADA.DM200TIT0401PV"]
    # tags = ["DMSCADA.410FIT1613PV.F_CV",
    #     "DMSCADA.410FIT1614PV.F_CV",
    #     "DMSCADA.410FIT1615PV.F_CV",
    #     "DMSCADA.410FIT1616PV.F_CV",
    #     "DMSCADA.410FIT1617PV.F_CV",
    #     "DMSCADA.410FIT1618PV.F_CV",
    #     "DMSCADA.410FIT1619PV.F_CV"]
    # tags = ["DMSCADA.120FI01_TOTAL_R.F_CV"]
    # tags = ['DM999FIT9120PV.F_CV']
    # tags = ['DMSCADA.AMP12002_SPEED.F_CV','DMSCADA.AMP12003_SPEED.F_CV',
    #         'DMSCADA.120FI01_TOTAL_R.F_CV','DMSCADA.DM200TIT0401PV']
    # time_range = [dt.datetime(2023,8,16,7),dt.datetime(2023,8,24,7)]
    # raw, dfl,dfw = datalake.query_ss_tag_and_range(ss_collection,time_range,tags)
    # dfw2 =dfw.resample("15T").mean()
    
    # #%%
    # mask = (dfl['local_time'] >= dt.datetime(2023,6,10,5)) & (dfl['local_time'] <= dt.datetime(2023,6,10,11,45))
    # subset = dfl[mask]
    #%% 
    
    # ss_collection = "ss_lims_clean"
    # tags = ['63','14','51','21','25']
    # tags = ['10','14','999','1002','51','4948']
    # tags = ['4948']
    # tags = ['61','63','1012','1011']
    # tags = ['14','51']
    # tags = ['61','51']
    # tags = ['4948','1118']
    # tags = ['63','14','51','21','25']
    # tags = ['63','14','51','21','25','61','39','1007']
    # time_range = [dt.datetime(2023,7,1,7),dt.datetime(2023,10,1,7)]
    # raw1, dfl1,dfw1 = datalake.query_ss_tag_and_range(ss_collection,time_range,tags)

    # ss_collection = "ss_frac_clean"
    # tags = ["Sumo__Plant__SmPCs__param__VSSinc_base"]
    # tags = ["Sumo__Plant__Blended__param__frSCCOD_TCOD"]
    # tags = ["Sumo__Plant__Blended__param__frTCOD_TKN"]
    # tags = ["Sumo__Plant__Blended__param__frTP_TKN"]
    # tags = ["Sumo__Plant__Blended__param__frVSS_TSS"]
    # time_range = [dt.datetime(2022,5,1,7),dt.datetime(2023,8,15,7)]
    # raw, dfl,dfw = datalake.query_ss_tag_and_range(ss_collection,time_range,tags)    
    
    # # %% test query_ss_results_time_range
    # time_range = [dt.datetime(2023,8,19,19),dt.datetime(2023,8,20,7)]
    # # tags = ['Sumo__Plant__param__Sumo1_Jacobs__qHAOH_AGING']
    # tags = ["Sumo__Plant__CombRaw_pipe__TCOD"]
    # # tags = ["Sumo__Plant__Blended__Q_recy","Sumo__Plant__CombRaw_pipe__Q"]
    # # tags = ["Sumo__Plant__PCAlum__Q"]
    # raw, dfl,dfw = datalake.query_ss_results_tag_and_range(time_range,tags)
    

    #%% test query_lims_earlier_time_of_one_tags_with_lastest_n_points
    # a = datalake.query_lims_earlier_time_of_one_tags_with_lastest_n_points(30, dt.datetime(2023,7,24),'1102')

    # %% test query_form_manual_setting
    # current_ts = dt.datetime(2023,8,15)
    # a = datalake.query_settings(current_ts,form = "manual")
    # b = datalake.query_settings(current_ts,form = "autocal")

    # # #%% test query_ss_frac_clean_lastest_n_points
    # current_ts = dt.datetime(2023,8,1)
    # tag = "Sumo__Plant__Blended__param__frVSS_TSS"
    # e = datalake.query_ss_frac_clean_lastest_n_points(60,current_ts,tag)
    # tag = "Sumo__Plant__Blended__param__frTCOD_TKN"
    # a = datalake.query_ss_frac_clean_lastest_n_points(60,current_ts,tag)
    # tag = "Sumo__Plant__Blended__param__frSCCOD_TCOD"
    # b = datalake.query_ss_frac_clean_lastest_n_points(60,current_ts,tag)
    # tag = "Sumo__Plant__Blended__param__frSPO4_TP"
    # c = datalake.query_ss_frac_clean_lastest_n_points(60,current_ts,tag)
    # tag = "Sumo__Plant__SmPCs__param__VSSinc_base"
    # tag = tags[0]
    # d = datalake.query_ss_frac_clean_lastest_n_points(60,current_ts,tag)
    
    # tag = "Sumo__Plant__Blended__param__frTP_TKN"
    # f = datalake.query_ss_frac_clean_lastest_n_points(60,current_ts,tag)
    # frac_long = pd.DataFrame()
    # tags = ["Sumo__Plant__Blended__param__frTCOD_TKN",
    #         "Sumo__Plant__Blended__param__frTP_TKN",
    #         "Sumo__Plant__Blended__param__frVSS_TSS",
    #         "Sumo__Plant__Blended__param__frSCCOD_TCOD",
    #         "Sumo__Plant__Blended__param__frVFA_SCCOD",
    #         "Sumo__Plant__Blended__param__frSNHx_TKN",
    #         "Sumo__Plant__Blended__param__frSPO4_TP",
    #         "Sumo__Plant__SmPCs__param__VSSinc_base"
    #                     ]
    # current_ts = dt.datetime(2023,8,1)
    # for a_tag in tags:
    #     temp = datalake.query_ss_frac_clean_lastest_n_points(60,current_ts,a_tag)
    #     import matplotlib.pyplot as plt
    #     fig, axs = plt.subplots(1,1,figsize= (16,4))
    #     ax = axs
    #     ax.plot(temp['ts'], temp['value'], marker="x", label=a_tag)
    #     ax.set_title(a_tag)
    #     ax.set_xlim([dt.datetime(2023,1,1), dt.datetime(2023,7,6)])
    #     ax.legend()
    #     fig_path = r"C:\Users\yangc2\OneDrive - Jacobs\HybridOptimizer\CWS_softsensor\figures"
    #     fig.savefig(os.path.join(fig_path,f"frac_{a_tag}.jpg"))
        
    # # %% test query_ss_lims_clean_lastest_n_points
    # current_ts = dt.datetime(2022,8,4)
    # tag = "1012"
    # a = datalake.query_ss_lims_clean_lastest_n_points(30,current_ts,tag)
    # b = datalake.query_lims_earlier_time_of_one_tags_with_lastest_n_points(30,current_ts,tag)
    
    #%% query auto
    # collection = datalake.yaml_dict["destination_db"]["form_autocal_settings"]
    # mycol = datalake.out_db[collection]
    # result= mycol.find({})
    # df = pd.DataFrame(result)
    
    # #%% query settings 
    # time_range = [dt.datetime(2023,6,9,19),dt.datetime(2023,6,11,7)]
    # tags = ['Sumo__Plant__param__Sumo1_Jacobs__qHAOH_AGING']
    # form = "autocal"
    # raw, dfl,dfw = datalake.query_settings_tag_and_range(form,time_range,tags)
    
    # x = datalake.query_settings(dt.datetime(2023,6,9,19),form = 'autocal')
    # out_df = tsv_history[-1].copy()
    # dfw1 = dfw.rename(columns = {tags[0]:"fake"})
    # out_df1 = pd.concat([out_df,dfw1],axis=1)
  #   #%% Fake insert data 
  #   import pytz
  #   TZ_UTC = pytz.timezone('UTC')
  #   TZ_SITE  = pytz.timezone('US/Pacific')
  #   ts_format = "%Y-%m-%d %H:%M:%S"
  #   pst_ts = TZ_SITE.localize(dt.datetime(1994,4,8,0,0,0))
  #   temp = {
  #   "ts": pst_ts.astimezone(TZ_UTC),
 	# "tag" : "1183",
 	# "value" : 0,
 	# "local_time" : "1994-04-08 00:00:00",
 	# "quality" : "good",
 	# "QAQC_violation" : [], 
 	# "inserted_at" : dt.datetime.now()
  #           }
  #   collection = datalake.yaml_dict["destination_db"]["ss_lims_clean"]
  #   datalake.out_db[collection].insert_one(temp)
  
    # #%% Test blob upload
    # source_file = r"C:\Users\yangc2\OneDrive - Jacobs\HybridOptimizer\CWS_softsensor\configurations\backup.xml"
    # destination_file = "default.xml"
    # datalake.upload_xml_to_blob(source_file=source_file,destination_file=destination_file)
    
    # #%% Test blob download
    # destination_file = r"C:\Users\yangc2\OneDrive - Jacobs\HybridOptimizer\CWS_softsensor\configurations\test.xml"
    # source_file = "default.xml"
    # datalake.download_xml_from_blob(source_file=source_file,destination_file=destination_file)
    

    
    

    # #%%
    # import matplotlib.pyplot as plt
    # # lims_w = lims_w.reset_index()
    # lims_w['MeasurementDate'] = pd.to_datetime(lims_w['MeasurementDate'])
    # fig, axs = plt.subplots(4,1,figsize= (12,12))
    # ax = axs[0]
    # ax.plot(dfw["Sumo__Plant__Blended__Q_recy"],label = "Recy_Q")
    # ax.legend()
    # ax = axs[1]
    # ax.plot(dfw["Sumo__Plant__CombRaw_pipe__Q"],label = "PI_Q")
    # ax.legend()
    # ax = axs[2]
    # ax.plot(lims_w['MeasurementDate'],lims_w["61"], marker="*", label= "PI_TP" )
    # ax.plot(lims_w['MeasurementDate'],lims_w["63"], marker="*", label= "PI_SP" )
    # # ax.set_xlim([dt.datetime(2023,6,17,7),dt.datetime(2023,7,6,7)])
    # ax.legend()
    # ax = axs[3]
    # ax.plot(lims_w['MeasurementDate'],lims_w["4937"], marker="*", label= "Recy_TP" )
    # ax.plot(lims_w['MeasurementDate'],lims_w["4948"], marker="*", label= "Recy_SP" )
    # # ax.set_xlim([dt.datetime(2023,6,17,7),dt.datetime(2023,7,6,7)])
    # ax.legend()
    
    # fig.tight_layout()
    # fig_path= r"C:\Users\yangc2\OneDrive - Jacobs\HybridOptimizer\CWS_softsensor\figures"
    # fig_name = os.path.join(fig_path,"recy_inves.jpg")
    # fig.savefig(fig_name)

    # #%%
    # tags = ['51','10','14','999','1002','61','63','4935','4937','4948','1012']
    # tags = ['1','1012']
    # time_range = [dt.datetime(2022,1,1,7),dt.datetime(2023,8,1,7)]
    # lims = datalake.query_lims_tag_and_range(time_range,tags)
    # lims_w  = lims.pivot_table(values = 'MeasuredValue', index='MeasurementDate',columns = 'MeasurementTag', dropna = False, aggfunc = "mean")
    
    # ss_collection = "ss_lims_clean"
    # tags = ['51','10','14','999','1002','61','63','4935','4937','4948','1012']
    # tags = ['1','1012']
    # time_range = [dt.datetime(2022,1,1,7),dt.datetime(2023,8,1,7)]
    # raw, dfl,dfw = datalake.query_ss_tag_and_range(ss_collection,time_range,tags)
    
    # tags = ["Sumo__Plant__PCAlum__Q","Sumo__Plant__CombPE_pipe__SPO4","Sumo__Plant__CombRaw_pipe__SPO4"]
    # raw, dfl,dfw = datalake.query_ss_results_tag_and_range(time_range,tags)
    # #%%
    # import matplotlib.pyplot as plt
    # fig, axs = plt.subplots(1,1,figsize= (16,4))
    # ax = axs
    # x_name = tags[0]
    # ax.plot(dfw.index, dfw[x_name ],label = x_name)
    # x_name = tags[1]
    # ax.plot(dfw.index, dfw[x_name ],label = x_name,color ='green')
    # x_name = tags[2]
    # ax.plot(dfw.index, dfw[x_name ],label = x_name,color ='red')
    # ax.scatter(lims_w.index,lims_w["63"], marker="o", label= "PI_SP",color ='black')
    # ax.scatter(lims_w.index,lims_w["1012"], marker="*", label= "PE_SP",color ='black')
    # ax.set_ylabel("Alum Q, m3/d or Conc, mg/L")
    # ax.legend()
    # ax.set_ylim([-1,17])
    # ax.set_xlim([dt.datetime(2023,4,1),dt.datetime(2023,7,5)])
    # fig.tight_layout()
    # fig_path= r"C:\Users\yangc2\OneDrive - Jacobs\HybridOptimizer\CWS_softsensor\figures"
    # fig_name = os.path.join(fig_path,"Alum_inves.jpg")
    # fig.savefig(fig_name)
    
# #%%
# dfl = scada.copy()
# inserted_at_list = dfl._ca.unique()
# for a_in in inserted_at_list:
#     print(f"_ca = {a_in}")
#     sub = dfl[dfl['_ca'] == a_in].copy()
#     if (a_in - sub['_ts'].max()) > dt.timedelta(hours =4):
#         print(f"  |-- start_ts: {sub['_ts'].min()}" )
#         print(f"  |-- end_ts: {sub['_ts'].max()}")
#         print(f"  |-- lag: {a_in - sub['_ts'].max() }")
#         print("/n")

# #%%    
# inserted_at_list = dfl.inserted_at.unique()
# for a_in in inserted_at_list:
#     print(f"_inserted_at = {a_in}")
#     sub = dfl[dfl['inserted_at'] == a_in].copy()
#     if (a_in - sub['local_time'].max()) > dt.timedelta(hours =4):
#         print(f"  |-- start_ts: {sub['local_time'].min()}" )
#         print(f"  |-- end_ts: {sub['local_time'].max()}")
#         print(f"  |-- lag: {a_in - sub['local_time'].max() }")
#         print("/n")

#%%
# sub = raw[(raw['tag'] == raw.tag.unique()[0]) & (raw['quality'] == 'good')].copy()
# sub = sub.sort_values(by=['ts','inserted_at'])
# sub = sub.drop_duplicates(subset = ['local_time', 'tag', 'value'], keep = 'first').copy()
# sub['lag'] = sub['inserted_at'] - sub['ts']
# inserted_at_list = sub.inserted_at.unique()
# for a_in in inserted_at_list:
#     print(f"_inserted_at = {a_in}")
#     sub2 = sub[sub['inserted_at'] == a_in].copy()
#     if (a_in - sub2['ts'].max()) > dt.timedelta(hours =4):
#         print(f"  |-- start_ts: {sub2['ts'].min()}" )
#         print(f"  |-- end_ts: {sub2['ts'].max()}")
#         print(f"  |-- lag: {a_in - sub['ts'].max() }")
#         print("/n")

#%% test query forecast_outputs 
    tags = ['Sumo__Plant__CombPE_pipe__SPO4']
    time_range = [dt.datetime(2023,10,1,7),dt.datetime(2023,10,25,7)]
    # time_range = [int(x.timestamp() * 1000) for x in time_range]
    # collection = datalake.yaml_dict["source_db"]["forecast_outputs"] # "forecast_outputs"
    # datalake_col_list = datalake.in_db.list_collection_names()
    # if collection in datalake_col_list:
    #     print(f" ---- Found the {collection}")
    # my_col = datalake.in_db[collection]
    # # Construct the query
    # query = {
    #     "_ts.$date": {
    #         "$gte": time_range[0],
    #         "$lte": time_range[1]
    #         }
    #     }
    # query = {"SUMO_encode_name": {"$in":tags}}
    # documents = my_col.find(query)
    # raw = pd.DataFrame(list(documents))
    # pipeline = [{"$match": {"SUMO_encode_name": {"$in":tags}}},
    #             {"$match": {"_ts.Date":{"$gte":time_range[0],"$lte":time_range[1]}}}]
    # raw = my_col.aggregate(pipeline)
    # raw = pd.DataFrame(raw)
    
    # def get_infl_forecasts(start_date, end_date, db):
    #     # Convert start and end date to timestamp format in milliseconds (as stored in your documents)
    #     start_timestamp = int(start_date.timestamp() * 1000)
    #     end_timestamp = int(end_date.timestamp() * 1000)
        
    #     # Construct the query
    #     query = {
    #         "_ts.$date": {
    #             "$gte": start_timestamp,
    #             "$lte": end_timestamp
    #         }
    #     }
    #     # Fetch documents from the collection using the query
    #     documents = db.find(query)
    #     return list(documents)

    # raw['MeasurementTime'] = pd.to_datetime(raw['MeasurementTime'])
    # # Create a pivot table from the DataFrame
    # dfw = raw.pivot_table(index='MeasurementTime', columns='SUMO_encode_name', values='value', aggfunc='last')
    df, dfw = datalake.query_forecast_outputs_tag_and_range(time_range, tags)
    
    #%%
    df = pd.DataFrame(datalake.out_db['forecast_current_ops'].find({}))