import {
  TwitterOutlined,
  YoutubeOutlined,
  PlaySquareOutlined,
  BookOutlined,
  RobotOutlined,
} from '@ant-design/icons';
import React from 'react';

export interface PlatformTheme {
  id: string;
  name: string;
  fullName: string;
  primaryColor: string;
  secondaryColor: string;
  bgGradient: string;
  IconComponent: React.ComponentType<any>;
  iconBg: string;
}

export const PLATFORM_THEMES: Record<string, PlatformTheme> = {
  x: {
    id: 'x',
    name: 'X (Twitter)',
    fullName: 'X Twitter 获客工作台',
    primaryColor: '#1DA1F2',
    secondaryColor: '#14171A',
    bgGradient: 'linear-gradient(135deg, #1DA1F215 0%, #1DA1F205 100%)',
    IconComponent: TwitterOutlined,
    iconBg: '#1DA1F2',
  },
  youtube: {
    id: 'youtube',
    name: 'YouTube',
    fullName: 'YouTube 获客工作台',
    primaryColor: '#FF0000',
    secondaryColor: '#282828',
    bgGradient: 'linear-gradient(135deg, #FF000015 0%, #FF000005 100%)',
    IconComponent: YoutubeOutlined,
    iconBg: '#FF0000',
  },
  bilibili: {
    id: 'bilibili',
    name: '哔哩哔哩',
    fullName: '哔哩哔哩获客工作台',
    primaryColor: '#00A1D6',
    secondaryColor: '#FB7299',
    bgGradient: 'linear-gradient(135deg, #00A1D615 0%, #FB729915 100%)',
    IconComponent: PlaySquareOutlined,
    iconBg: '#00A1D6',
  },
  kuaishou: {
    id: 'kuaishou',
    name: '快手',
    fullName: '快手获客工作台',
    primaryColor: '#FF4906',
    secondaryColor: '#FF7E33',
    bgGradient: 'linear-gradient(135deg, #FF490615 0%, #FF7E3315 100%)',
    IconComponent: PlaySquareOutlined,
    iconBg: '#FF4906',
  },
  douyin: {
    id: 'douyin',
    name: '抖音',
    fullName: '抖音获客工作台',
    primaryColor: '#000000',
    secondaryColor: '#FE2C55',
    bgGradient: 'linear-gradient(135deg, #00000015 0%, #FE2C5515 100%)',
    IconComponent: RobotOutlined,
    iconBg: '#000000',
  },
  xhs: {
    id: 'xiaohongshu',
    name: '小红书',
    fullName: '小红书获客工作台',
    primaryColor: '#FE2C55',
    secondaryColor: '#FF2442',
    bgGradient: 'linear-gradient(135deg, #FE2C5515 0%, #FF244205 100%)',
    IconComponent: BookOutlined,
    iconBg: '#FE2C55',
  },
};

export const PLATFORM_LIST = Object.values(PLATFORM_THEMES);

export const getPlatformTheme = (platformId: string): PlatformTheme => {
  // 1. 直接按 key 查（如 "x", "youtube", "douyin", "bilibili", "xhs"）
  if (PLATFORM_THEMES[platformId]) {
    return PLATFORM_THEMES[platformId];
  }
  // 2. 按 id 字段查（selector 传的是 id，如小红书的 "xiaohongshu" 而非 key "xhs"）
  const byId = PLATFORM_LIST.find((p) => p.id === platformId);
  if (byId) {
    return byId;
  }
  // 3. 兜底返回 X 主题
  return PLATFORM_THEMES.x;
};
