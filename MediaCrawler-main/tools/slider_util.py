# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tools/slider_util.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。


# -*- coding: utf-8 -*-
# @Author  : relakkes@gmail.com
# @Time    : 2023/12/2 12:55
# @Desc    : Slider verification utility package
import os
from typing import List
from urllib.parse import urlparse

import cv2
import httpx
import numpy as np


class Slide:
    """
    copy from https://blog.csdn.net/weixin_43582101 thanks for author
    update: relakkes
    """
    def __init__(self, gap, bg, gap_size=None, bg_size=None, out=None):
        """
        :param gap: Gap image path or url
        :param bg: Background image with gap path or url
        """
        self.img_dir = os.path.join(os.getcwd(), 'temp_image')
        if not os.path.exists(self.img_dir):
            os.makedirs(self.img_dir)

        bg_resize = bg_size if bg_size else (340, 212)
        gap_size = gap_size if gap_size else (68, 68)
        self.bg = self.check_is_img_path(bg, 'bg', resize=bg_resize)
        self.gap = self.check_is_img_path(gap, 'gap', resize=gap_size)
        self.out = out if out else os.path.join(self.img_dir, 'out.jpg')

    @staticmethod
    def check_is_img_path(img, img_type, resize):
        if img.startswith('http'):
            # 重试机制：滑块图片 URL 可能是临时签名，偶尔 404，重试可解决
            max_retries = 3
            last_error = None
            for attempt in range(max_retries):
                try:
                    headers = {
                        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                        "Accept-Language": "zh-CN,zh;q=0.9",
                        "Connection": "keep-alive",
                        "Referer": "https://rmc.bytedance.com/",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    }
                    img_res = httpx.get(img, headers=headers, follow_redirects=True, timeout=10)
                    if img_res.status_code != 200:
                        last_error = f"HTTP {img_res.status_code}"
                        if attempt < max_retries - 1:
                            import time
                            time.sleep(0.5)
                            continue
                        raise Exception(f"Failed to download {img_type} image: HTTP {img_res.status_code}")

                    # 调试日志：检查下载内容
                    content_type = img_res.headers.get('content-type', 'unknown')
                    content_len = len(img_res.content)
                    print(f"[slider_util] {img_type} image: HTTP {img_res.status_code}, content-type={content_type}, length={content_len}")
                    # 如果内容很短，可能是错误响应（如 JSON 错误信息）
                    if content_len < 500:
                        print(f"[slider_util] {img_type} response body (too short): {img_res.text[:300]}")

                    # 解码图片，检查是否为有效图片
                    image = np.asarray(bytearray(img_res.content), dtype="uint8")
                    image = cv2.imdecode(image, cv2.IMREAD_COLOR)
                    if image is None:
                        last_error = "imdecode returned None (not a valid image)"
                        # 保存原始响应以便调试
                        try:
                            debug_path = f'./temp_image/{img_type}_debug.bin'
                            with open(debug_path, 'wb') as f:
                                f.write(img_res.content)
                            print(f"[slider_util] {img_type} raw response saved to {debug_path} for debugging")
                        except Exception:
                            pass
                        if attempt < max_retries - 1:
                            import time
                            time.sleep(0.5)
                            continue
                        raise Exception(f"Failed to decode {img_type} image: {last_error}")

                    if resize:
                        image = cv2.resize(image, dsize=resize)

                    img_path = f'./temp_image/{img_type}.jpg'
                    cv2.imwrite(img_path, image)
                    return img_path

                except httpx.RequestError as e:
                    last_error = str(e)
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(0.5)
                        continue
                    raise Exception(f"Failed to download {img_type} image: {last_error}")

            raise Exception(f"Failed to save {img_type} image after {max_retries} retries: {last_error}")
        else:
            return img

    @staticmethod
    def clear_white(img):
        """Clear whitespace from image, mainly clearing slider whitespace"""
        img = cv2.imread(img)
        if img is None:
            raise Exception("clear_white: failed to read image (cv2.imread returned None)")
        rows, cols, channel = img.shape
        min_x = 255
        min_y = 255
        max_x = 0
        max_y = 0
        for x in range(1, rows):
            for y in range(1, cols):
                t = set(img[x, y])
                if len(t) >= 2:
                    if x <= min_x:
                        min_x = x
                    elif x >= max_x:
                        max_x = x

                    if y <= min_y:
                        min_y = y
                    elif y >= max_y:
                        max_y = y
        img1 = img[min_x:max_x, min_y: max_y]
        return img1

    def template_match(self, tpl, target):
        th, tw = tpl.shape[:2]
        result = cv2.matchTemplate(target, tpl, cv2.TM_CCOEFF_NORMED)
        # Find min and max value positions in matrix
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        tl = max_loc
        br = (tl[0] + tw, tl[1] + th)
        # Draw rectangle border to mark the matched area
        # target: target image
        # tl: rectangle top-left corner
        # br: rectangle width and height
        # (0,0,255): rectangle border color
        # 1: rectangle border size
        cv2.rectangle(target, tl, br, (0, 0, 255), 2)
        cv2.imwrite(self.out, target)
        return tl[0]

    @staticmethod
    def image_edge_detection(img):
        edges = cv2.Canny(img, 100, 200)
        return edges

    def discern(self):
        """识别滑块缺口位置

        关键修复: 抖音验证码的 gap 图(滑块图)通过元素截图获取时，
        没有透明/白色边框，导致 clear_white 失效，模板匹配会在背景图
        左上角(x=0~2)产生误匹配(val高达0.998)。
        修复方法: 所有模板匹配都屏蔽 x<50 的区域(滑块起始位置在最左，
        缺口不可能在最左边)，用边缘匹配作为主要方法。
        """
        # 缺口最小 x 坐标(屏蔽左侧误匹配区域)
        MIN_GAP_X = 50

        bg_img = cv2.imread(self.bg, cv2.IMREAD_COLOR)
        gap_img_raw = cv2.imread(self.gap, cv2.IMREAD_COLOR)
        if bg_img is None or gap_img_raw is None:
            return 0

        bg_gray = cv2.cvtColor(bg_img, cv2.COLOR_BGR2GRAY)
        gap_gray = cv2.cvtColor(gap_img_raw, cv2.COLOR_BGR2GRAY)

        # 方法1(主要): 边缘模板匹配 - 屏蔽 x<50
        # gap 边缘(滑块形状)与 bg 边缘(缺口轮廓)匹配
        x_edge = -1
        val_edge = -1
        try:
            gap_blur = cv2.GaussianBlur(gap_gray, (3, 3), 0)
            bg_blur = cv2.GaussianBlur(bg_gray, (3, 3), 0)
            gap_edge = cv2.Canny(gap_blur, 50, 150)
            bg_edge = cv2.Canny(bg_blur, 50, 150)
            result = cv2.matchTemplate(bg_edge, gap_edge, cv2.TM_CCOEFF_NORMED)
            # 屏蔽 x<50 的列，避免左上角误匹配
            result[:, :MIN_GAP_X] = -1
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            x_edge = max_loc[0]
            val_edge = max_val
            # 可视化
            cv2.rectangle(bg_img, (x_edge, max_loc[1]),
                          (x_edge + gap_img_raw.shape[1], max_loc[1] + gap_img_raw.shape[0]),
                          (0, 0, 255), 2)
            cv2.imwrite(self.out, bg_img)
        except Exception:
            x_edge = -1

        # 方法2(备选): 轮廓检测从背景图找缺口阴影
        x_contour = self._detect_gap_by_contour()

        # 方法3(辅助): 灰度模板匹配 - 屏蔽 x<50
        x_gray = -1
        val_gray = -1
        try:
            result_g = cv2.matchTemplate(bg_gray, gap_gray, cv2.TM_CCOEFF_NORMED)
            result_g[:, :MIN_GAP_X] = -1
            min_val_g, max_val_g, min_loc_g, max_loc_g = cv2.minMaxLoc(result_g)
            x_gray = max_loc_g[0]
            val_gray = max_val_g
        except Exception:
            x_gray = -1

        # 综合判断
        # 优先级: 边缘匹配 > 轮廓检测 > 灰度匹配
        # 边缘匹配对截图场景最可靠(已验证能正确定位到 x=233)
        print(f"[slider_util.discern] edge: x={x_edge}, val={val_edge:.4f}", flush=True)
        print(f"[slider_util.discern] contour: x={x_contour}", flush=True)
        print(f"[slider_util.discern] gray: x={x_gray}, val={val_gray:.4f}", flush=True)
        print(f"[slider_util.discern] bg shape={bg_img.shape}, gap shape={gap_img_raw.shape}", flush=True)
        candidates = []
        if x_edge >= MIN_GAP_X:
            candidates.append((x_edge, val_edge, "edge"))
        if x_contour >= MIN_GAP_X:
            candidates.append((x_contour, 1.0, "contour"))
        if x_gray >= MIN_GAP_X:
            candidates.append((x_gray, val_gray, "gray"))

        if not candidates:
            # 所有方法都失败，返回最大的(可能仍>0)
            return max([x_edge, x_contour, x_gray], default=0)

        if len(candidates) == 1:
            return candidates[0][0]

        # 多个候选: 找最接近的一对取平均
        candidates.sort(key=lambda c: c[0])
        values = [c[0] for c in candidates]
        # 找最接近的一对
        close_pairs = [(abs(values[i] - values[j]), (values[i] + values[j]) / 2)
                       for i in range(len(values)) for j in range(i + 1, len(values))]
        close_pairs.sort(key=lambda x: x[0])
        if close_pairs and close_pairs[0][0] < 40:
            # 两个方法结果接近(<40px)，取平均
            return int(close_pairs[0][1])

        # 结果分散，优先用边缘匹配(最可靠)
        for x, v, name in candidates:
            if name == "edge":
                return x
        # 其次轮廓检测
        for x, v, name in candidates:
            if name == "contour":
                return x
        return candidates[0][0]

    def _detect_gap_by_contour(self):
        """通过轮廓检测从背景图中直接找缺口位置 - 比模板匹配更可靠"""
        try:
            bg_img = cv2.imread(self.bg, cv2.IMREAD_COLOR)
            if bg_img is None:
                return -1
            
            # 转灰度
            gray = cv2.cvtColor(bg_img, cv2.COLOR_BGR2GRAY)
            
            # 高斯模糊去噪
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            
            # 边缘检测 - 使用更敏感的阈值
            edged = cv2.Canny(blurred, 30, 120)
            
            # 膨胀操作，让边缘更连续
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            edged = cv2.dilate(edged, kernel, iterations=1)
            
            # 查找轮廓
            contours, _ = cv2.findContours(edged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # 筛选可能是缺口的轮廓
            bg_h, bg_w = bg_img.shape[:2]
            min_area = 1500
            max_area = 8000
            candidates = []
            
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                area = cv2.contourArea(contour)
                
                # 缺口特征筛选
                if (min_area < area < max_area and 
                    40 < w < 90 and 40 < h < 90 and
                    0.6 < w/h < 1.5 and
                    x > 50):  # 缺口不会在最左边
                    candidates.append((x, y, w, h, area))
            
            if not candidates:
                # 放宽条件重试
                for contour in contours:
                    x, y, w, h = cv2.boundingRect(contour)
                    area = cv2.contourArea(contour)
                    if (800 < area < 12000 and 
                        30 < w < 100 and 30 < h < 100 and
                        0.5 < w/h < 2.0 and
                        x > 40):
                        candidates.append((x, y, w, h, area))
            
            if not candidates:
                return -1
            
            # 按面积排序，取最可能是缺口的
            candidates.sort(key=lambda c: c[4], reverse=True)
            
            # 取第一个候选的 x 坐标（缺口的左边缘）
            best = candidates[0]
            gap_x = best[0]
            
            # 绘制标记
            cv2.rectangle(bg_img, (best[0], best[1]), (best[0]+best[2], best[1]+best[3]), (0, 0, 255), 2)
            cv2.imwrite(self.out, bg_img)
            
            return gap_x
            
        except Exception as e:
            return -1

    def _multi_method_match(self, tpl, target):
        """多种匹配方法综合判断，提高识别准确率"""
        import logging
        th, tw = tpl.shape[:2]
        
        # 方法1: TM_CCOEFF_NORMED (原方法)
        result1 = cv2.matchTemplate(target, tpl, cv2.TM_CCOEFF_NORMED)
        min_val1, max_val1, min_loc1, max_loc1 = cv2.minMaxLoc(result1)
        
        # 方法2: TM_CCORR_NORMED (相关性匹配)
        result2 = cv2.matchTemplate(target, tpl, cv2.TM_CCORR_NORMED)
        min_val2, max_val2, min_loc2, max_loc2 = cv2.minMaxLoc(result2)
        
        # 方法3: 对边缘增强后的图像进行匹配
        # 先对模板和目标做高斯模糊减少噪声
        tpl_blur = cv2.GaussianBlur(tpl, (3, 3), 0)
        target_blur = cv2.GaussianBlur(target, (3, 3), 0)
        result3 = cv2.matchTemplate(target_blur, tpl_blur, cv2.TM_CCOEFF_NORMED)
        min_val3, max_val3, min_loc3, max_loc3 = cv2.minMaxLoc(result3)
        
        # 选择置信度最高的结果
        results = [
            (max_val1, max_loc1[0], "CCOEFF"),
            (max_val2, max_loc2[0], "CCORR"),
            (max_val3, max_loc3[0], "CCOEFF_BLUR"),
        ]
        results.sort(key=lambda x: x[0], reverse=True)
        
        best_score, best_x, best_method = results[0]
        
        # 如果前两个方法结果接近，取平均
        if abs(results[0][1] - results[1][1]) < 10:
            best_x = int((results[0][1] + results[1][1]) / 2)
        
        # 绘制标记
        tl = (best_x, 0)
        br = (best_x + tw, th)
        cv2.rectangle(target, tl, br, (0, 0, 255), 2)
        cv2.imwrite(self.out, target)
        
        return best_x


def get_track_simple(distance) -> List[int]:
    """生成拟人滑块轨迹 - 模拟真人拖动：快速接近→减速→微调→停顿"""
    import random
    track: List[int] = []
    current = 0
    # 三段式：加速段(0-60%) → 减速段(60-90%) → 微调段(90-100%)
    phase1_end = distance * random.uniform(0.55, 0.70)
    phase2_end = distance * random.uniform(0.85, 0.95)
    t = random.uniform(0.12, 0.20)
    v = random.uniform(0.8, 2.0)

    while current < distance:
        if current < phase1_end:
            # 加速段：较大的正向加速度
            a = random.uniform(4, 7)
        elif current < phase2_end:
            # 减速段：负向加速度，逐渐减速
            a = random.uniform(-5, -2)
        else:
            # 微调段：很小的速度，模拟精确对准
            a = random.uniform(-1.5, 1.5)
            v = min(v, 1.5)

        v0 = v
        v = v0 + a * t
        v = max(v, 0.3)  # 速度不低于0.3
        move = v0 * t + 0.5 * a * t * t

        # 随机抖动（模拟手部不稳）
        if random.random() < 0.12:
            move += random.uniform(-0.8, 0.8)

        current += move
        track.append(round(move))

    # 末尾精确对准：可能超过目标，需要回拉
    overshoot = current - distance
    if overshoot > 2 and len(track) > 0:
        # 超过目标，回拉
        track[-1] = track[-1] - round(overshoot)
        # 随机加一个小的回弹
        if random.random() < 0.4:
            track.append(round(random.uniform(-1.5, -0.3)))
            track.append(round(random.uniform(0.3, 1.5)))
    elif overshoot < -2 and len(track) > 0:
        # 不到目标，前推
        track[-1] = track[-1] + round(abs(overshoot))
    else:
        # 微调范围内，偶尔加一个停顿后的微调
        if random.random() < 0.3:
            track.append(round(random.uniform(-0.5, 0.5)))

    return track


def get_tracks(distance: int, level: str = "easy") -> List[int]:
    if level == "easy":
        return get_track_simple(distance)
    else:
        from . import easing
        _, tricks = easing.get_tracks(distance, seconds=2, ease_func="ease_out_expo")
        return tricks
