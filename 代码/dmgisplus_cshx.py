#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 测试参数
# http://localhost:7707/pws/CallPlugin/model?methodName=cshx&postdata=gxyulin|2024-09-27 20:00:00|20

"""
玉林城市火险预警分析Python插件
"""
import shutil
import sys
import os
import json
import io
import time

import requests
import configparser
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
TEST_MODE = True
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

class CShxAnalysis:
    """城市火险预警分析模型类"""

    def __init__(self, server_name: str):
        self.server_name = server_name
        self.myDB = DbConfig(server_name)
        self.com = Common()
        self.basepath = self.myDB.configPath
        self.downloadpath = self.myDB.fileSavePath
        self.dmCom = DmMapCom()

        self.qybrlt = []  # 保存计算完成的结果集
        self.yzVal = []
        self.clrVal = []

    def loadYz(self, dateTime_str: str) -> list:
        """加载火险因子配置"""
        listA = []
        try:
            dt_obj = datetime.strptime(dateTime_str, "%Y-%m-%d %H:%M:%S")
            month = dt_obj.month

            if 3 <= month <= 5:
                condition = "3,5"
            elif 6 <= month <= 8:
                condition = "6,8"
            elif 9 <= month <= 11:
                condition = "9,11"
            else:
                condition = "12,2"

            param = f"month='{condition}' or month is null"
            cols = ["weatherfactor", "month", "minvalue", "maxvalue", "exponentialcomponent"]

            data = DataServiceOperate.http_request_post(
                self.myDB.fw_url, "cshx_yz", "select", param,
                advcode=self.myDB.dm_advcode, columns=cols
            )

            if not data:
                return listA

            for icon in data:
                icon_month = icon.get("month")
                if icon_month and str(icon_month) != condition:
                    continue

                max_raw = icon.get("maxvalue")
                min_raw = icon.get("minvalue")
                yz_raw = icon.get("exponentialcomponent")

                listA.append({
                    "element": str(icon.get("weatherfactor", "")),
                    # 拦截 None 和空字符串，赋予极限值保障区间逻辑闭合
                    "max": float(max_raw) if max_raw not in (None, "") else 9999.0,
                    "min": float(min_raw) if min_raw not in (None, "") else -99.0,
                    "yz": float(yz_raw) if yz_raw not in (None, "") else 0.0
                })
        except Exception:
            pass
        return listA

    def getFireLevel(self, yz: int) -> str:
        """根据火险指数获取火险等级"""
        cols = ["id", "colour", "value"]
        sort_opt = ["id"]
        data = DataServiceOperate.http_request_post(
            self.myDB.fw_url, "cshx_setting", "select", "",
            advcode=self.myDB.dm_advcode, columns=cols, sort=sort_opt
        )

        if not data or len(data) < 4:
            return "5级"

        try:
            val_0 = float(data[0].get("value", 0))
            val_1 = float(data[1].get("value", 0))
            val_2 = float(data[2].get("value", 0))
            val_3 = float(data[3].get("value", 0))

            if yz <= val_0:
                return "1级"
            elif (val_0 + 1) <= yz <= val_1:
                return "2级"
            elif (val_1 + 1) <= yz <= val_2:
                return "3级"
            elif (val_2 + 1) <= yz <= val_3:
                return "4级"
            else:
                return "5级"
        except Exception:
            return "5级"

    def cshxAnlysis(self, date_str: str, sc: str, codename: str) -> bool:
        """城市火险核心分析逻辑"""
        gridpath = os.path.join(self.basepath, "result", f"{codename}.grid")
        if os.path.exists(gridpath):
            return True

        vecWorkShop = VecWorkShop()
        workpath = os.path.join(self.basepath, "经纬度", "城区.sda")

        try:
            cqno = vecWorkShop.OpenAreaWork(workpath)
            if cqno < 0:
                return False
            areawork = vecWorkShop.GetWorkByNo(cqno)

            dmCutPart = Se_Part()
            areawork.GetObjPos(0, dmCutPart)

            # 1. 得到在城区内的预报站点信息 township_forecast_province（wlmqC++那边调的是省台乡镇预报，但玉林这边没给它入库，直接用乡镇预报表）
            cols_fcst = [
                "stationid", "stationname", "longitude", "latitude",
                "min(COALESCE(CAST(NULLIF(TRIM(CAST(humid AS text)), '') AS numeric), 0)) as humid",
                "max(COALESCE(CAST(NULLIF(TRIM(CAST(maxtemp AS text)), '') AS numeric), 0)) as maxtemp",
                "max(COALESCE(CAST(NULLIF(TRIM(CAST(winds AS text)), '') AS numeric), 0)) as winds",
                "sum(COALESCE(CAST(NULLIF(TRIM(CAST(rain AS text)), '') AS numeric), 0)) as rain"
            ]
            param_fcst = f"dateChar='{date_str}' and timechar='{sc}' and ntimes<=24 "
            fcst_data = DataServiceOperate.http_request_post(self.myDB.qx_url, "township_forecast",
                                                             "select", param_fcst, columns=cols_fcst)

            city_list = []
            if fcst_data:
                for icon in fcst_data:
                    dt = Dt()
                    dt.x = float(icon.get("longitude", 0))
                    dt.y = float(icon.get("latitude", 0))

                    if self.dmCom.ptinpolygons1(dt, dmCutPart) > 0:
                        city_list.append({
                            "name": str(icon.get("stationname", "")),
                            "id": str(icon.get("stationid", "")),
                            "lon": dt.x,
                            "lat": dt.y,
                            "ybMinRelHumidity": float(icon.get("humid", 0)),
                            "ybMaxTemp": float(icon.get("maxtemp", 0)),
                            "ybMaxWindS": float(icon.get("winds", 0)),
                            "ybRain": float(icon.get("rain", 0)),
                            "noRainDay": 0
                        })

            # 2. 得到在城区内的连续无降水天数 msgmediumsmallscale
            cols_obs = ["stationname", "max(observtime) as observtime"]
            date_time_full = f"{date_str} {sc}:00:00"  # 重构 dateTime
            param_obs = f"observTime<='{date_time_full}' and rain>0"
            obs_data_qx = DataServiceOperate.http_request_post(self.myDB.qx_url, "msgmediumsmallscale",
                                                               "select", param_obs, columns=cols_obs)

            obs_list = []
            if obs_data_qx:
                for icon in obs_data_qx:
                    obs_list.append({
                        "stationname": str(icon.get("stationname", "")),
                        "observtime": str(icon.get("observtime", ""))
                    })

            # 3. 计算特殊站点的预报 tour_fcst 和实况 tour_smallscale
            param_tour = f"dateChar='{date_str}' and timechar='{sc}' and ntimes<= 24  and forecasttype = 12"
            tour_data = DataServiceOperate.http_request_post(self.myDB.fw_url, "tour_fcst", "select", param_tour,
                                                             advcode=self.myDB.dm_advcode, columns=cols_fcst)

            if tour_data:
                for icon in tour_data:
                    dt = Dt()
                    dt.x = float(icon.get("longitude", 0))
                    dt.y = float(icon.get("latitude", 0))

                    if self.dmCom.ptinpolygons1(dt, dmCutPart) > 0:
                        city_list.append({
                            "name": str(icon.get("stationname", "")),
                            "id": str(icon.get("stationid", "")),
                            "lon": dt.x,
                            "lat": dt.y,
                            "ybMinRelHumidity": float(icon.get("humid", 0)),
                            "ybMaxTemp": float(icon.get("maxtemp", 0)),
                            "ybMaxWindS": float(icon.get("winds", 0)),
                            "ybRain": float(icon.get("rain", 0)),
                            "noRainDay": 0
                        })

            obs_data_fw = DataServiceOperate.http_request_post(self.myDB.fw_url, "tour_smallscale", "select", param_obs,
                                                               advcode=self.myDB.dm_advcode, columns=cols_obs)
            if obs_data_fw:
                for icon in obs_data_fw:
                    obs_list.append({
                        "stationname": str(icon.get("stationname", "")),
                        "observtime": str(icon.get("observtime", ""))
                    })

            # 计算连续无雨日数
            dt_end = datetime.strptime(date_time_full, "%Y-%m-%d %H:%M:%S")
            for city in city_list:
                if city["ybRain"] > 0:
                    city["noRainDay"] = 0
                    continue

                if not obs_list:
                    continue

                for obs in obs_list:
                    if obs["stationname"].strip() == city["name"]:
                        try:
                            dt_start = datetime.strptime(obs["observtime"][:10], "%Y-%m-%d")
                            dt_end_only = datetime.strptime(date_time_full[:10], "%Y-%m-%d")
                            dd = (dt_end_only - dt_start).days
                            city["noRainDay"] = dd
                        except Exception:
                            pass

            if not city_list:
                return False

            # 4. 删除同日期的旧数据并查询因子
            delete_param = f"forcastdate='{date_time_full}'"

            DataServiceOperate.http_request_post(
                self.myDB.fw_url, "cshx_zsyb", "delete", delete_param,
                advcode=self.myDB.dm_advcode
            )

            yzList = self.loadYz(date_time_full)

            # 5. 根据因子和数据计算等级
            self.qybrlt = []
            num_inserted = 0

            for city in city_list:
                valrel = city["ybMinRelHumidity"]
                valtemp = city["ybMaxTemp"]
                valwind = city["ybMaxWindS"]
                valRain = city["ybRain"]
                valno = city["noRainDay"]

                # 应用权重
                for yz in yzList:
                    if yz["element"] == "日最高气温" and yz["min"] <= valtemp <= yz["max"]:
                        city["ybMaxTemp"] = yz["yz"]
                    elif yz["element"] == "日最小相对湿度" and yz["min"] <= valrel <= yz["max"]:
                        city["ybMinRelHumidity"] = yz["yz"]
                    elif yz["element"] == "日最大风速" and yz["min"] <= valwind <= yz["max"]:
                        city["ybMaxWindS"] = yz["yz"]
                    elif yz["element"] == "连续无降水日数" and yz["min"] <= valno <= yz["max"]:
                        city["noRainDay"] = yz["yz"]
                    elif yz["element"] == "日降水量" and yz["min"] <= valRain <= yz["max"]:
                        city["ybRain"] = yz["yz"]

                sumYz = int(
                    city["ybMaxTemp"] + city["ybMinRelHumidity"] + city["ybMaxWindS"] + city["noRainDay"] + city[
                        "ybRain"])
                firelevel = self.getFireLevel(sumYz)

                insert_data = {
                    "stationid": city["id"],
                    "forcastdate": date_time_full,
                    "humidity": city["ybMinRelHumidity"],
                    "noraincomponent": city["noRainDay"],
                    "tempcomponent": city["ybMaxTemp"],
                    "windcomponent": city["ybMaxWindS"],
                    "raincomponent": city["ybRain"],
                    "fireindex": sumYz,
                    "firelevel": firelevel,
                    "lon": city["lon"],
                    "lat": city["lat"],
                    "stationname": city["name"]
                }

                self.qybrlt.append(insert_data)

                # 单条插入
                msg = DataServiceOperate.http_request_post(
                    self.myDB.fw_url, "cshx_zsyb", "insert", "",
                    advcode=self.myDB.dm_advcode, data=insert_data
                )

                if msg and isinstance(msg, list) and len(msg) > 0:
                    num_inserted += 1

            if num_inserted > 0:
                return True

            return False

        except Exception as e:
            return False
        finally:
            vecWorkShop.delete()

    def DrawWarningArea(self, codename: str) -> str:
        """生成预警区矢量与JSON结果"""
        gridpath = os.path.join(self.basepath, "result", f"{codename}.grid")

        #少于3个点无法构建三角网，直接返回
        if not os.path.exists(gridpath):
            if len(self.qybrlt) < 3:
                return "[]"

        dtmWorkShop = DtmWorkShop()
        graphWorkShop = GraphWorkShop()
        vecWorkShop = VecWorkShop()

        try:
            # 1. 如果Grid不存在，先生成Grid
            if not os.path.exists(gridpath):
                if len(self.qybrlt) < 3:
                    return "[]"

                workpath = os.path.join(self.basepath, "经纬度", "城区.sda")
                cqno = vecWorkShop.OpenAreaWork(workpath)
                if cqno < 0:
                    return ""
                areawork = vecWorkShop.GetWorkByNo(cqno)

                rct = Rct()
                areawork.GetObjRect(0, rct)

                contour = Tin()
                for pt in self.qybrlt:
                    contour.addpoint(pt["lon"], pt["lat"], float(pt["fireindex"]))
                contour.calculate4pintzvalue(rct)
                contour.dmmesh()

                grid_base_path = os.path.join(self.basepath, "GRID", "城区分析GRID.grid")
                ai_base = dtmWorkShop.OpenGridWork(grid_base_path)
                if ai_base < 0:
                    return ""
                analyseGrid = dtmWorkShop.GetWorkByNo(ai_base)

                grd = Grid()
                grd.setgridwork(analyseGrid)
                grd.addcontour(contour, 1, 1)

                # 必须确保 result 文件夹存在
                os.makedirs(os.path.dirname(gridpath), exist_ok=True)
                analyseGrid.UpdateZMaxMin()
                analyseGrid.WriteFile(gridpath)

                # 重新关闭以释放旧句柄，为后续打开新生成的Grid做准备
                dtmWorkShop.delete()
                dtmWorkShop = DtmWorkShop()

            # 2. 读取 Grid 并生成等值面矢量
            ai = dtmWorkShop.OpenGridWork(gridpath)
            if ai < 0:
                return "openfail"
            gridwork = dtmWorkShop.GetWorkByNo(ai)

            ai_graph = graphWorkShop.CreateGraphWork()
            yjhand = graphWorkShop.GetWorkByNo(ai_graph)

            # 获取展示设置
            if not self.yzVal:
                sort_opt = ["value asc"]
                data = DataServiceOperate.http_request_post(
                    self.myDB.fw_url, "cshx_setting", "select", "",
                    advcode=self.myDB.dm_advcode, sort=sort_opt
                )

                self.yzVal.clear()
                self.clrVal.clear()
                for icon in data:
                    self.yzVal.append(float(icon.get("value", 0)))
                    self.clrVal.append(int(icon.get("colour", 0)))

            if not self.yzVal:
                return ""

            # 追踪等值面
            grd = Grid()
            grd.setgridwork(gridwork)
            pset = [v for v in self.yzVal]
            grd.tracefillsign(len(pset), pset, self.clrVal, yjhand)

            # 输出面模板
            areapath = os.path.join(self.basepath, "map", "行政区划", "dzmCshx.sda")
            ai_area = vecWorkShop.CreateAreaWork(areapath)
            areawork_out = vecWorkShop.GetWorkByNo(ai_area) if ai_area >= 0 else None

            num = yjhand.GetObjNum()
            partArr = []

            for m in range(num):
                ainf = AInf()
                yjhand.GetObjInf(m, ainf)
                wgobj = yjhand.GetObj(m)

                dtst = Se_Dtst()
                wgobj.GetObjPos(dtst)
                pt_list = dtst.toList()

                level = ""
                for i in range(len(self.yzVal)):
                    if self.clrVal[i] == ainf.col:
                        level = str(i)

                json_obj = {
                    "color": str(ainf.col),
                    "level": level,
                    "codenumber": codename,
                    "posArr": []
                }

                if areawork_out:
                    part = Se_Part()
                    part.SetSize([len(pt_list)])
                    for i, pt in enumerate(pt_list):
                        part.SetPos(i, pt)
                        json_obj["posArr"].append({"lon": round(pt.x, 5), "lat": round(pt.y, 5)})
                    areawork_out.AddObj(part, ainf)

                partArr.append(json_obj)

            if areawork_out:
                areawork_out.SaveWork()

            return self.com.ResultObj_Arr(200, "查询成功", partArr)

        except Exception as e:
            return ""
        finally:
            dtmWorkShop.delete()
            graphWorkShop.delete()
            vecWorkShop.delete()


def runService(className: str, methodName: str, postdata: str) -> str:
    """
    主服务函数
    className="model",
    methodName="cshx",
    postdata="serverName|datetime|shici"
    """
    try:
        import urllib.parse
        if '%' in postdata:
            postdata = urllib.parse.unquote(postdata)

        if className == "model":
            paramlist = postdata.split("|")
            if methodName == "cshx":
                if len(paramlist) != 3:
                    return "参数有误"

                serverName = paramlist[0]
                datetime_str = paramlist[1]
                shici = paramlist[2]

                try:
                    datetime_obj = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    datetime_obj = datetime.now()

                codename = "cshx" + datetime_obj.strftime("%Y%m%d%H%M%S")
                date_only = datetime_obj.strftime("%Y-%m-%d")

                model = CShxAnalysis(serverName)
                flag = model.cshxAnlysis(date_only, shici, codename)

                result = "[]"
                if flag:
                    result = model.DrawWarningArea(codename)

                if result in ["", "openfail"]:
                    return "[]"

                return result

        return ""

    except Exception as e:
        # 服务执行异常也做降级处理
        return "[]"


if __name__ == "__main__":
    if len(sys.argv) >= 4:
        # 服务平台调用模式
        TEST_MODE = True
        result = runService(sys.argv[1], sys.argv[2], sys.argv[3])
        print(result)
    else:
        # 开启本地调试模式
        TEST_MODE = True
        test_json = {
            "className": "model",
            "methodName": "cshx",
            "postdata": "gxyulin|2026-06-11 08:00:00|08"
        }
        result = runService(
            className=test_json["className"],
            methodName=test_json["methodName"],
            postdata=test_json["postdata"]
        )
        print(result)