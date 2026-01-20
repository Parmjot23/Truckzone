import * as React from 'react';
import { View, Linking, ScrollView } from 'react-native';
import { List, Divider, Button, Text, useTheme } from 'react-native-paper';
import Constants from 'expo-constants';
import { useAuth } from '@/state/auth/AuthContext';

export function SettingsScreen() {
	const { logout } = useAuth();
	const theme = useTheme();
  const appVersion = (Constants?.expoConfig as any)?.version || (Constants?.manifest as any)?.version || '1.0.0';
	return (
		<View style={{ flex: 1, backgroundColor: theme.colors.background }}>
			<ScrollView contentContainerStyle={{ padding: 16 }}>
				<Text variant="headlineSmall" style={{ marginBottom: 12 }}>Settings</Text>

        {/* Account */}
				<List.Section>
          <List.Subheader>Account</List.Subheader>
					<List.Item title="Logout" description="Sign out of your account" left={(props) => <List.Icon {...props} icon="logout" />} onPress={logout} />
				</List.Section>

        <Divider />

        {/* Legal */}
				<List.Section>
          <List.Subheader>Legal</List.Subheader>
					<List.Item title="Privacy Policy" left={(props) => <List.Icon {...props} icon="shield-lock-outline" />} onPress={() => Linking.openURL('https://www.smart-invoices.com/privacy-policy/')} />
					<List.Item title="Terms & Conditions" left={(props) => <List.Icon {...props} icon="file-document-outline" />} onPress={() => Linking.openURL('https://www.smart-invoices.com/terms-and-conditions/')} />
					<List.Item title="Cookies Policy" left={(props) => <List.Icon {...props} icon="cookie-outline" />} onPress={() => Linking.openURL('https://www.smart-invoices.com/cookies_policy/')} />
				</List.Section>

        <Divider />

        {/* Help */}
        <List.Section>
          <List.Subheader>Help</List.Subheader>
          <List.Item title="Website" description="www.smart-invoices.com" left={(props) => <List.Icon {...props} icon="web" />} onPress={() => Linking.openURL('https://www.smart-invoices.com/')} />
          <List.Item title="Tutorials" left={(props) => <List.Icon {...props} icon="school-outline" />} onPress={() => Linking.openURL('https://www.smart-invoices.com/tutorials/')} />
          <List.Item title="Contact Support" description="Accounts@smart-invoices.com" left={(props) => <List.Icon {...props} icon="email-outline" />} onPress={() => Linking.openURL('mailto:Accounts@smart-invoices.com')} />
        </List.Section>

        <Divider />

        {/* About */}
        <List.Section>
          <List.Subheader>About</List.Subheader>
          <List.Item title={`Version ${appVersion}`} left={(props) => <List.Icon {...props} icon="information-outline" />} />
        </List.Section>

			</ScrollView>
		</View>
	);
}