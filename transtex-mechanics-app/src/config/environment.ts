import Constants from 'expo-constants';

type ExtraConfig = {
  apiBaseUrl?: string;
};

function resolveExtraConfig(): ExtraConfig {
  const expoConfig = Constants.expoConfig as { extra?: ExtraConfig } | undefined;
  if (expoConfig?.extra) {
    return expoConfig.extra;
  }

  const manifest = Constants.manifest as { extra?: ExtraConfig } | null | undefined;
  if (manifest?.extra) {
    return manifest.extra;
  }

  const manifest2 = (Constants as any)?.manifest2;
  const manifest2Extra = manifest2?.extra?.expoClient?.extra as ExtraConfig | undefined;
  if (manifest2Extra) {
    return manifest2Extra;
  }

  return {};
}

export function getApiBaseUrl(): string {
  const extra = resolveExtraConfig();
  return (
    extra.apiBaseUrl ||
    process.env.EXPO_PUBLIC_API_BASE_URL ||
    'https://www.itranstech.ca/api'
  );
}
