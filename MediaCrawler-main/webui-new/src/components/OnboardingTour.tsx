import React, { useEffect, useState, useMemo } from 'react';
import { Tour } from 'antd';
import type { TourProps } from 'antd';

/**
 * 首次使用引导(Onboarding)
 *
 * - 首次登录(localStorage 标记缺失)自动启动 5 步引导
 * - 完成或跳过后写入标记,后续不再弹出
 * - 提供"再次查看"入口:window.__restartOnboarding()
 *
 * 使用 Antd 6 原生 Tour 组件,无需引入 react-joyride 等第三方依赖。
 */

const STORAGE_KEY = 'onboarding_completed_v1';

const OnboardingTour: React.FC = () => {
  const [open, setOpen] = useState(false);

  // 通过文本匹配菜单项元素(Antd Menu 的 li 文本即 label)
  const findMenuItem = (text: string): HTMLElement | null => {
    const items = document.querySelectorAll<HTMLElement>('.ant-menu-item');
    for (const el of Array.from(items)) {
      if (el.textContent?.includes(text)) return el;
    }
    return null;
  };

  const steps: TourProps['steps'] = useMemo(() => [
    {
      title: '欢迎使用获客系统',
      description: '本系统帮助你从社交平台识别潜在客户、跟进转化。下面用 1 分钟了解核心流程。',
      // 无 target:居中显示
    },
    {
      title: '第 1 步:创建获客任务',
      description: '在这里创建采集任务,设置关键词和目标平台。系统会自动扫描评论,识别潜在客户。',
      target: () => findMenuItem('获客中心') as HTMLElement,
    },
    {
      title: '第 2 步:查看客户线索',
      description: '采集到的潜在客户会沉淀到这里。支持列表/看板视图、多维度筛选、拖拽变更状态,也能导入外部线索。',
      target: () => findMenuItem('客户线索') as HTMLElement,
    },
    {
      title: '第 3 步:我的套餐',
      description: '在「我的」中查看套餐状态、用量统计、余额充值,以及 Cookie 管理。',
      target: () => findMenuItem('我的') as HTMLElement,
    },
    {
      title: '第 4 步:个性化设置',
      description: '在「设置」中可配置意向评分规则、关键词分类、Webhook 通知等。需要帮助随时联系管理员。',
      target: () => findMenuItem('设置') as HTMLElement,
    },
  ], []);

  const start = () => {
    // 等菜单渲染完成再启动,避免 target 为空
    setTimeout(() => setOpen(true), 300);
  };

  useEffect(() => {
    // 已完成引导则跳过
    if (localStorage.getItem(STORAGE_KEY)) return;
    start();

    // 暴露重新启动入口(供"再次查看"按钮调用)
    (window as any).__restartOnboarding = () => {
      localStorage.removeItem(STORAGE_KEY);
      start();
    };

    return () => {
      delete (window as any).__restartOnboarding;
    };
  }, []);

  const handleClose = () => {
    setOpen(false);
    localStorage.setItem(STORAGE_KEY, '1');
  };

  return (
    <Tour
      open={open}
      onClose={handleClose}
      steps={steps}
      indicatorsRender={(current, total) => (
        <span style={{ color: '#999', fontSize: 12 }}>
          {current + 1} / {total}
        </span>
      )}
    />
  );
};

export default OnboardingTour;
