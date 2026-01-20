import React, { useState, useRef } from 'react';
import { View, StyleSheet, Alert, TouchableOpacity } from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { Button, Text, ActivityIndicator, Surface } from 'react-native-paper';
import { MaterialIcons } from '@expo/vector-icons';
import type { ParamListBase } from '@react-navigation/native';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import { uploadJobPhoto } from '@/services/mediaService';

type RootStackParamList = ParamListBase & {
  PhotoCapture: { jobId: string };
};

type Props = NativeStackScreenProps<RootStackParamList, 'PhotoCapture'>;

export function PhotoCaptureScreen({ navigation, route }: Props) {
  const { jobId } = route.params;
  const [permission, requestPermission] = useCameraPermissions();
  const [isUploading, setIsUploading] = useState(false);
  const cameraRef = useRef<CameraView>(null);

  if (!permission) {
    return <View />;
  }

  if (!permission.granted) {
    return (
      <View style={styles.container}>
        <Surface style={styles.permissionContainer}>
          <MaterialIcons name="camera-alt" size={64} color="#666" />
          <Text variant="headlineSmall" style={styles.permissionTitle}>
            Camera Permission Required
          </Text>
          <Text variant="bodyMedium" style={styles.permissionText}>
            We need camera permission to capture job photos.
          </Text>
          <Button
            mode="contained"
            onPress={requestPermission}
            style={styles.permissionButton}
          >
            Grant Permission
          </Button>
        </Surface>
      </View>
    );
  }

  const takePicture = async () => {
    if (cameraRef.current && !isUploading) {
      try {
        const photo = await cameraRef.current.takePictureAsync({
          quality: 0.7,
          base64: false,
        });

        if (photo?.uri) {
          setIsUploading(true);
          try {
            await uploadJobPhoto(jobId, photo.uri);
            Alert.alert(
              'Success',
              'Photo uploaded successfully!',
              [{ text: 'OK', onPress: () => navigation.goBack() }]
            );
          } catch (error) {
            Alert.alert(
              'Upload Failed',
              'Failed to upload photo. Please try again.',
              [{ text: 'OK' }]
            );
          } finally {
            setIsUploading(false);
          }
        }
      } catch (error) {
        Alert.alert('Error', 'Failed to take picture. Please try again.');
      }
    }
  };

  return (
    <View style={styles.container}>
      <CameraView
        ref={cameraRef}
        style={styles.camera}
        facing="back"
      >
        <View style={styles.overlay}>
          <View style={styles.header}>
            <TouchableOpacity
              onPress={() => navigation.goBack()}
              style={styles.backButton}
            >
              <MaterialIcons name="arrow-back" size={24} color="white" />
            </TouchableOpacity>
            <Text variant="titleMedium" style={styles.title}>
              Capture Photo
            </Text>
          </View>

          <View style={styles.controls}>
            {isUploading ? (
              <View style={styles.uploadingContainer}>
                <ActivityIndicator size="large" color="white" />
                <Text variant="bodyLarge" style={styles.uploadingText}>
                  Uploading photo...
                </Text>
              </View>
            ) : (
              <TouchableOpacity
                onPress={takePicture}
                style={styles.captureButton}
              >
                <View style={styles.captureButtonInner}>
                  <MaterialIcons name="camera" size={32} color="white" />
                </View>
              </TouchableOpacity>
            )}
          </View>
        </View>
      </CameraView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: 'black',
  },
  camera: {
    flex: 1,
  },
  overlay: {
    flex: 1,
    backgroundColor: 'transparent',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingTop: 50,
    paddingHorizontal: 20,
    paddingBottom: 20,
  },
  backButton: {
    padding: 8,
    borderRadius: 20,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
  },
  title: {
    color: 'white',
    marginLeft: 16,
    fontWeight: 'bold',
  },
  controls: {
    flex: 1,
    justifyContent: 'flex-end',
    alignItems: 'center',
    paddingBottom: 40,
  },
  captureButton: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  captureButtonInner: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: 'rgba(255, 255, 255, 0.3)',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 4,
    borderColor: 'white',
  },
  uploadingContainer: {
    alignItems: 'center',
  },
  uploadingText: {
    color: 'white',
    marginTop: 16,
  },
  permissionContainer: {
    flex: 1,
    margin: 20,
    padding: 24,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 12,
  },
  permissionTitle: {
    marginTop: 16,
    marginBottom: 8,
    textAlign: 'center',
  },
  permissionText: {
    textAlign: 'center',
    marginBottom: 24,
    color: '#666',
  },
  permissionButton: {
    minWidth: 150,
  },
});