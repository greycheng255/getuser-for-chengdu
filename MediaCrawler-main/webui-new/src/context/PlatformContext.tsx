import React, { createContext, useContext, useState, useCallback, useMemo } from 'react';
import { getPlatformTheme, type PlatformTheme } from '../constants/platformThemes';

interface PlatformContextValue {
  platform: string;
  theme: PlatformTheme;
  setPlatform: (platform: string) => void;
}

const PlatformContext = createContext<PlatformContextValue | null>(null);

export const PlatformProvider: React.FC<{
  defaultPlatform?: string;
  children: React.ReactNode;
}> = ({ defaultPlatform = 'x', children }) => {
  const [platform, setPlatform] = useState<string>(defaultPlatform);

  const theme = useMemo(() => getPlatformTheme(platform), [platform]);

  const handleSetPlatform = useCallback((p: string) => {
    setPlatform(p);
  }, []);

  const value = useMemo(
    () => ({
      platform,
      theme,
      setPlatform: handleSetPlatform,
    }),
    [platform, theme, handleSetPlatform]
  );

  return (
    <PlatformContext.Provider value={value}>
      {children}
    </PlatformContext.Provider>
  );
};

export const usePlatform = (): PlatformContextValue => {
  const ctx = useContext(PlatformContext);
  if (!ctx) {
    throw new Error('usePlatform must be used within PlatformProvider');
  }
  return ctx;
};
