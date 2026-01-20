import * as React from 'react';
import * as Network from 'expo-network';

export type QueuedItem = {
  id: string;
  type: 'photo' | 'status' | 'note' | 'parts';
  payload: any;
};

const UploadQueueContext = React.createContext<{ enqueue: (item: QueuedItem) => void } | undefined>(undefined);

export function UploadQueueProvider({ children }: { children: React.ReactNode }) {
  const enqueue = (item: QueuedItem) => {
    console.log('queued', item.id);
  };
  return <UploadQueueContext.Provider value={{ enqueue }}>{children}</UploadQueueContext.Provider>;
}

export function useUploadQueue() {
  const ctx = React.useContext(UploadQueueContext);
  if (!ctx) throw new Error('useUploadQueue must be used within UploadQueueProvider');
  return ctx;
}

export function useOfflineQueueProcessor() {
  React.useEffect(() => {
    const subscription = Network.addNetworkStateListener((state) => {
      if (state.isConnected) {
        // flush queue (stub)
      }
    });
    return () => subscription.remove();
  }, []);
}