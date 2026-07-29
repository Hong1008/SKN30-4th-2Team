import React, { createContext, useContext, useEffect, useState } from 'react';
import { MetadataData } from '../types';
import { api } from '../api/api';

interface MetadataContextValue {
  metadata: MetadataData | null;
  isLoading: boolean;
  error: Error | null;
}

const MetadataContext = createContext<MetadataContextValue>({
  metadata: null,
  isLoading: true,
  error: null,
});

export const useMetadata = () => useContext(MetadataContext);

export function MetadataProvider({ children }: { children: React.ReactNode }) {
  const [metadata, setMetadata] = useState<MetadataData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let mounted = true;

    async function fetchMetadata() {
      try {
        const response = await api.getMetadata();
        if (mounted) {
          setMetadata(response.data);
          setIsLoading(false);
        }
      } catch (err: any) {
        if (mounted) {
          setError(err);
          setIsLoading(false);
        }
      }
    }

    fetchMetadata();

    return () => {
      mounted = false;
    };
  }, []);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="text-center">
          <div className="w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
          <p className="text-sm text-slate-500 font-medium">서비스 환경 설정 중...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="text-center p-6 bg-white rounded-2xl shadow-sm border border-rose-200">
          <p className="text-sm text-rose-600 font-bold mb-2">설정 정보를 불러오지 못했습니다.</p>
          <p className="text-xs text-slate-500 mb-4">
            서버 설정 정보를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.
          </p>
          <button 
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-slate-900 text-white text-xs font-semibold rounded-lg hover:bg-slate-800"
          >
            다시 시도
          </button>
        </div>
      </div>
    );
  }

  return (
    <MetadataContext.Provider value={{ metadata, isLoading, error }}>
      {children}
    </MetadataContext.Provider>
  );
}
