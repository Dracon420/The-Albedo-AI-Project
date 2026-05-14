import { useCallback, useRef } from 'react';
import { Audio } from 'expo-av';
import * as FileSystem from 'expo-file-system';

// ── Recording options ─────────────────────────────────────────────────────────
// iOS  → Linear PCM WAV  (native, no conversion needed by server)
// Android → MPEG-4 / AAC (Android cannot produce WAV natively;
//           the server's soundfile + ffmpeg handles decoding)

const RECORDING_OPTIONS: Audio.RecordingOptions = {
  isMeteringEnabled: false,
  ios: {
    extension: '.wav',
    outputFormat: Audio.IOSOutputFormat.LINEARPCM,
    audioQuality: Audio.IOSAudioQuality.HIGH,
    sampleRate: 16000,
    numberOfChannels: 1,
    bitRate: 128000,
    linearPCMBitDepth: 16,
    linearPCMIsBigEndian: false,
    linearPCMIsFloat: false,
  },
  android: {
    extension: '.m4a',
    outputFormat: Audio.AndroidOutputFormat.MPEG_4,
    audioEncoder: Audio.AndroidAudioEncoder.AAC,
    sampleRate: 16000,
    numberOfChannels: 1,
    bitRate: 128000,
  },
  web: {
    mimeType: 'audio/webm',
    bitsPerSecond: 128000,
  },
};

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useAudioRecorder() {
  const recordingRef = useRef<Audio.Recording | null>(null);

  const startRecording = useCallback(async (): Promise<void> => {
    // Request mic permission
    const { status } = await Audio.requestPermissionsAsync();
    if (status !== 'granted') {
      throw new Error('Microphone permission denied. Enable it in device Settings.');
    }

    // Put audio session into recording mode (required on iOS)
    await Audio.setAudioModeAsync({
      allowsRecordingIOS: true,
      playsInSilentModeIOS: true,
    });

    const recording = new Audio.Recording();
    await recording.prepareToRecordAsync(RECORDING_OPTIONS);
    await recording.startAsync();
    recordingRef.current = recording;
  }, []);

  const stopRecording = useCallback(async (): Promise<string | null> => {
    const recording = recordingRef.current;
    if (!recording) return null;
    recordingRef.current = null;

    await recording.stopAndUnloadAsync();

    // Return audio session to playback mode
    await Audio.setAudioModeAsync({
      allowsRecordingIOS: false,
      playsInSilentModeIOS: true,
    });

    return recording.getURI() ?? null;
  }, []);

  return { startRecording, stopRecording };
}

// ── Playback ──────────────────────────────────────────────────────────────────

/**
 * Decode a base64-encoded WAV string and play it through the device speaker.
 * Writes a temp file to the cache directory, plays it, then cleans up.
 */
export async function playAudioBase64(base64: string): Promise<void> {
  const uri = `${FileSystem.cacheDirectory}albedo_${Date.now()}.wav`;

  await FileSystem.writeAsStringAsync(uri, base64, {
    encoding: FileSystem.EncodingType.Base64,
  });

  await Audio.setAudioModeAsync({
    allowsRecordingIOS: false,
    playsInSilentModeIOS: true,
    staysActiveInBackground: false,
  });

  const { sound } = await Audio.Sound.createAsync(
    { uri },
    { shouldPlay: true, volume: 1.0 },
  );

  await new Promise<void>((resolve) => {
    sound.setOnPlaybackStatusUpdate((ps) => {
      if (!ps.isLoaded) return;
      if (ps.didJustFinish) {
        sound.unloadAsync().catch(() => {});
        FileSystem.deleteAsync(uri, { idempotent: true }).catch(() => {});
        resolve();
      }
    });
  });
}
