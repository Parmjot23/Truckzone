import * as BackgroundFetch from 'expo-background-fetch';
import * as TaskManager from 'expo-task-manager';
import { QueryClient } from '@tanstack/react-query';

const TASK_NAME = 'background-sync-jobs';

TaskManager.defineTask(TASK_NAME, async () => {
  try {
    // In a real app, fetch and update cache here
    return BackgroundFetch.BackgroundFetchResult.NewData;
  } catch (e) {
    return BackgroundFetch.BackgroundFetchResult.Failed;
  }
});

export async function registerBackgroundSync() {
  try {
    await BackgroundFetch.registerTaskAsync(TASK_NAME, {
      minimumInterval: 15 * 60,
      stopOnTerminate: false,
      startOnBoot: true,
    });
  } catch (e) {
    // ignore in dev simulator
  }
}