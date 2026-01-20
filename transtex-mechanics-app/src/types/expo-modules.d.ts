declare module 'expo-print' {
  type PrintToFileOptions = {
    html: string;
    width?: number;
    height?: number;
    base64?: boolean;
  };

  type PrintOptions = {
    html: string;
    printerUrl?: string;
  };

  export function printAsync(options: PrintOptions): Promise<void>;
  export function printToFileAsync(options: PrintToFileOptions): Promise<{ uri: string; base64?: string }>;
}

declare module 'expo-sharing' {
  type ShareOptions = {
    mimeType?: string;
    dialogTitle?: string;
    UTI?: string;
  };

  export function isAvailableAsync(): Promise<boolean>;
  export function shareAsync(url: string, options?: ShareOptions): Promise<void>;
}
