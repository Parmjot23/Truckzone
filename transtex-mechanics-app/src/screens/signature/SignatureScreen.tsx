import * as React from 'react';
import { View } from 'react-native';
import { Button } from 'react-native-paper';
import SignatureCanvas from 'react-native-signature-canvas';
import { useNavigation, useRoute } from '@react-navigation/native';
import { apiClient } from '@/services/apiClient';

export function SignatureScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const jobId = route.params?.jobId as string;
  const ref = React.useRef<any>(null);

  const handleOK = (signature: string) => {
    // signature is a base64 png URI
    apiClient.post(`/jobs/${jobId}/signature/`, { dataUrl: signature })
      .then(() => navigation.goBack())
      .catch(() => navigation.goBack());
  };

  return (
    <View style={{ flex: 1 }}>
      <SignatureCanvas
        ref={ref}
        onOK={handleOK}
        onEmpty={() => {}}
        descriptionText="Sign to complete job"
        clearText="Clear"
        confirmText="Save"
        webStyle={".m-signature-pad--footer {position: absolute; bottom: 0; width: 100%;}"}
      />
      <Button onPress={() => ref.current?.clearSignature?.()}>Clear</Button>
    </View>
  );
}