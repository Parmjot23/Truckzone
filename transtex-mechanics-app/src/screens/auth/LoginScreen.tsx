import * as React from 'react';
import { View } from 'react-native';
import { Button, TextInput, Text, useTheme, Card } from 'react-native-paper';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import { useAuth } from '@/state/auth/AuthContext';

const schema = z.object({
  identifier: z.string().min(1),
  password: z.string().min(1),
});

type FormValues = z.infer<typeof schema>;

export function LoginScreen() {
  const { login } = useAuth();
  const theme = useTheme();
  const [submitError, setSubmitError] = React.useState<string | null>(null);
  const { control, handleSubmit, setValue, formState: { errors, isSubmitting } } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { identifier: '', password: '' },
  });

  const onSubmit = async (values: FormValues) => {
    setSubmitError(null);
    try {
      await login(values.identifier, values.password);
    } catch (e: any) {
      const msg = e?.response?.data?.error || e?.message || 'Login failed';
      setSubmitError(typeof msg === 'string' ? msg : 'Login failed');
      throw e;
    }
  };

  return (
    <View style={{ flex: 1 }}>
      {/* Gradient background */}
      <View style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: '#2f63d1' }} />
      <View style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '60%', backgroundColor: '#2a5298' }} />
      <View style={{ position: 'absolute', top: '40%', left: 0, right: 0, bottom: 0, backgroundColor: '#f5f7fb', borderTopLeftRadius: 24, borderTopRightRadius: 24 }} />

      <View style={{ flex: 1, padding: 16, alignItems: 'center', justifyContent: 'center' }}>
        <Card style={{ width: '100%', maxWidth: 420, elevation: 6 }}>
          <Card.Content>
            <Text variant="headlineSmall" style={{ color: theme.colors.primary, textAlign: 'center', marginBottom: 4 }}>Welcome</Text>
            <Text style={{ color: theme.colors.onSurfaceVariant, textAlign: 'center', marginBottom: 8 }}>Sign in to the mechanic portal</Text>

            <TextInput
              label="Email or Username"
              autoCapitalize="none"
              onChangeText={(t) => setValue('identifier', t)}
              style={{ marginBottom: 8 }}
              error={!!errors.identifier}
            />
            <TextInput
              label="Password"
              secureTextEntry
              onChangeText={(t) => setValue('password', t)}
              style={{ marginBottom: 8 }}
              error={!!errors.password}
            />
            {(errors.identifier || errors.password) && (
              <Text style={{ color: 'red', marginBottom: 8, textAlign: 'center' }}>Please check your inputs</Text>
            )}
            {submitError ? (
              <Text style={{ color: 'red', marginBottom: 8, textAlign: 'center' }}>{submitError}</Text>
            ) : null}
            <Button mode="contained" onPress={handleSubmit(onSubmit)} loading={isSubmitting}>
              Login
            </Button>
          </Card.Content>
        </Card>
      </View>
    </View>
  );
}