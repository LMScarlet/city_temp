#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 测试参数
# http://localhost:7707/pws/CallPlugin/model?methodName=待补充

"""
XXXXXXPython插件
"""
import shutil
import sys
import os
import json
import time
import io
import requests
import configparser
import urllib.parse
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 导入DMGIS Python SDK
from dmgis.common.dmsde import GridDataInfo, AInf, Rct, Dt
from dmgis.common.Se_Part import Se_Part
from dmgis.common.Se_Dtst import Se_Dtst
from dmgis.dtm.Grid import Grid
from dmgis.dtm.Tin import Tin
from dmgis.work.DtmWorkShop import DtmWorkShop
from dmgis.work.GraphWorkShop import GraphWorkShop
from dmgis.work.VecWorkShop import VecWorkShop
from dmgis.common.DmMapCom import DmMapCom

# ================= 调试模式路径配置 =================
TEST_MODE = False
TEST_BASE_DIR = r"D:\dmgisqt1.0\program"  # 服务平台路径
# =======================================================

class DbConfig:
    """路径与配置管理类"""
    def __init__(self, server_name: str):
        self.base_dir = TEST_BASE_DIR if TEST_MODE else os.getcwd()

        # 配置文件路径
        self.configPath = os.path.join(self.base_dir, "DmCloudService", "PluginLibrary", server_name)
        # 通用函数临时路径（必须）
        self.tempPath = os.path.join(self.base_dir, "DmCloudService", "PluginLibrary", "temp")
        # 插件图片缓存地址
        self.fileSavePath = os.path.join(self.base_dir, "DmCloudService", "PluginLibrary", "temp")
        self.dm_GridSavePath = os.path.join(self.base_dir, "DmCloudService", "PluginLibrary", f"temp{server_name}",
                                            "grid_file")

        self.dmMapCom = DmMapCom()
        self.dmMapCom.SetTempPath(self.tempPath)
        # 符号库路径
        self.slibPath = os.path.join(self.base_dir, "slib")

        self.qx_url = ""
        self.fw_url = ""
        self.mongo_url = ""
        self.xmin = ""
        self.xmax = ""
        self.ymin = ""
        self.ymax = ""
        self.dm_WaterLimit = ""
        self.resServer_url = ""
        self.dm_advcode = ""
        self.dm_advcity = ""
        self.dm_advcounty = ""

        self.configInfo()

    def configInfo(self):
        """读取配置文件"""
        filepath = os.path.join(self.configPath, "SysConfig", "sysconfig.ini")
        if os.path.exists(filepath):
            config = configparser.ConfigParser()
            config.read(filepath, encoding='utf-8')

            # pg数据库服务接口
            if config.has_option("PGDataServer", "qx_url"):
                self.qx_url = config.get("PGDataServer", "qx_url")
            if config.has_option("PGDataServer", "fw_url"):
                self.fw_url = config.get("PGDataServer", "fw_url")
            if config.has_option("MongoServer", "mongo_url"):
                self.mongo_url = config.get("MongoServer", "mongo_url")

            # 坐标
            if config.has_option("area", "xmin"):
                self.xmin = config.get("area", "xmin")
            if config.has_option("area", "xmax"):
                self.xmax = config.get("area", "xmax")
            if config.has_option("area", "ymin"):
                self.ymin = config.get("area", "ymin")
            if config.has_option("area", "ymax"):
                self.ymax = config.get("area", "ymax")

            if config.has_option("shlimit", "waterlimit"):
                self.dm_WaterLimit = config.get("shlimit", "waterlimit")

            if config.has_option("mapserver", "resurl"):
                self.resServer_url = config.get("mapserver", "resurl")

            if config.has_option("advinfo", "advcode"):
                self.dm_advcode = config.get("advinfo", "advcode")
            if config.has_option("advinfo", "advcity"):
                self.dm_advcity = config.get("advinfo", "advcity")
            if config.has_option("advinfo", "advcounty"):
                self.dm_advcounty = config.get("advinfo", "advcounty")

class DataServiceOperate:
    """网络服务与数据操作类"""

    @staticmethod
    def get_param_str(table: str, sql_type: str, param_dict: dict, advcode: str) -> str:
        """组装PG数据库请求参数"""
        param_json = json.dumps(param_dict, separators=(',', ':'))
        return f"method={table}&sqlType={sql_type}&advCode={advcode}&param={param_json}"

    @staticmethod
    def http_request_post(url: str, table: str, sql_type: str, param_condition: str, advcode: str = "",
                          columns: list = None, sort: list = None, data=None):
        """
        发送HTTP POST请求执行数据库操作
        支持 select, insert, update, delete 及批量插入
        """
        if not url: return []

        param_dict = {"param": param_condition}

        if sql_type == "select":
            if columns: param_dict["columns"] = columns
            if sort: param_dict["sort"] = sort

        if data is not None:
            param_dict["data"] = data

        payload = DataServiceOperate.get_param_str(table, sql_type, param_dict, advcode)

        try:
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}
            response = requests.post(url, data=payload.encode('utf-8'), headers=headers, timeout=15)
            if response.status_code == 200:
                res_json = response.json()

                if isinstance(res_json, list): return res_json
                if isinstance(res_json, dict) and "data" in res_json: return res_json["data"]

                return [res_json]
        except Exception:
            pass
        return []

    @staticmethod
    def exist_mongo_file(url: str, condition: str, collection_name: str, advcode: str = "") -> bool:
        """判断Mongo中是否存在目标文件"""
        if not url: return False
        payload = f"sqlType=exist&{condition}&collectionName={collection_name}&advCode={advcode}"
        try:
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}
            response = requests.post(url, data=payload.encode('utf-8'), headers=headers, timeout=15)
            if response.status_code == 200:
                return int(response.text.strip()) > 0
        except Exception:
            pass
        return False

    @staticmethod
    def operate_mongo_file(url: str, operate: str, condition: str, collection_name: str, file_path: str = "",
                           advcode: str = "") -> bool:
        """执行Mongo文件的上传、下载、更新与删除"""
        if not url: return False

        query_string = f"?sqlType={operate}&{condition}&collectionName={collection_name}"
        if advcode:
            query_string += f"&advCode={advcode}"
        full_url = url + query_string

        try:
            if operate == "select":
                response = requests.get(full_url, stream=True, timeout=30)
                if response.status_code == 200 and len(response.content) > 100:
                    if file_path:
                        with open(file_path, 'wb') as f:
                            f.write(response.content)
                    return True

            elif operate in ["insert", "update"]:
                if not os.path.exists(file_path): return False
                with open(file_path, 'rb') as f:
                    files = {'file': (os.path.basename(file_path), f, 'application/octet-stream')}
                    response = requests.post(full_url, files=files, timeout=30)
                    if response.status_code == 200:
                        return int(response.text.strip()) > 0

            elif operate == "delete":
                response = requests.get(full_url, timeout=15)
                if response.status_code == 200:
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def clear_temp_files_by_hours(folder_path: str, max_hour: int):
        """按时间戳清理缓存目录下的过期文件"""
        if not os.path.exists(folder_path): return
        current_time = time.time()
        max_age = max_hour * 3600

        for root, dirs, files in os.walk(folder_path, topdown=False):
            for name in files:
                file_path = os.path.join(root, name)
                try:
                    if current_time - os.path.getctime(file_path) > max_age:
                        os.remove(file_path)
                except Exception:
                    pass
            for name in dirs:
                dir_path = os.path.join(root, name)
                try:
                    if not os.listdir(dir_path):
                        os.rmdir(dir_path)
                except Exception:
                    pass

    @staticmethod
    def clear_temp_files(folder_path: str, max_cache: int):
        """按文件数量上限清理缓存目录"""
        if not os.path.exists(folder_path): return

        items = []
        for name in os.listdir(folder_path):
            full_path = os.path.join(folder_path, name)
            items.append((full_path, os.path.getctime(full_path)))

        if len(items) > max_cache:
            items.sort(key=lambda x: x[1])
            items_to_delete = items[:(len(items) - max_cache)]

            for path, _ in items_to_delete:
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                    elif os.path.isdir(path):
                        shutil.rmtree(path)
                except Exception:
                    pass

class Common:
    """公共工具类"""
    def __init__(self):
        pass

    def GetStringByPos_Part(self, col: int, part: Se_Part, level: str) -> str:
        strval = f"{col}#"
        try:
            partnum = part.GetPartSize()
            for i in range(partnum):
                dtst = part.GetDtst(i)
                if not dtst: continue
                pt_list = dtst.toList()
                for pt in pt_list:
                    strval += f"{pt.x:.5f} {pt.y:.5f},"
                strval = strval.rstrip(",")
                if level:
                    strval += f"#{level}"
                strval += "*"
        except Exception:
            pass
        return strval.rstrip("*")

    def GetStringByPos_Dtst(self, col: int, dtst: Se_Dtst, level: str) -> str:
        strval = f"{col}#"
        pt_list = dtst.toList()
        for pt in pt_list:
            strval += f"{pt.x:.5f} {pt.y:.5f},"
        strval = strval.rstrip(",")
        if level:
            strval += f"#{level}"
        return strval

    def ResultObj_Arr(self, code: int, message: str, dataArr: list) -> str:
        json_obj = {"code": code, "message": message, "data": dataArr}
        return json.dumps(json_obj, ensure_ascii=False)

    def ResultObj_Dict(self, code: int, message: str, dataObj: dict) -> str:
        json_obj = {"code": code, "message": message, "data": dataObj}
        return json.dumps(json_obj, ensure_ascii=False)

class XXXXXAnalysis:
    """核心功能类，视不同插件情况修改"""
【待填补】


def runService(className: str, methodName: str, postdata: str) -> str:
    """
    主服务函数
    className="model",
    methodName="gxyulin",
    postdata="serverName|xxxxx|xxxx……"
    """
    【待填补】


if __name__ == "__main__":
    if len(sys.argv) >= 4:
        # 服务平台调用模式
        TEST_MODE = False
        result = runService(【参数待补】)
        print(result)
    else:
        # 开启本地调试模式
        TEST_MODE = True
        test_json = {
            "className": "model",
            "methodName": "gxyulin",
            "postdata": 【参数待补】
        }
        result = runService(
            className=test_json["className"],
            methodName=test_json["methodName"],
            postdata=test_json["postdata"]
        )
        print(result)