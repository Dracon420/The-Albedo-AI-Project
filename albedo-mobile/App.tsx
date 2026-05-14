import React, { useCallback, useEffect, useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  SafeAreaView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useFonts, ShareTechMono_400Regular } from '@expo-google-fonts/share-tech-mono';
import { MaterialCommunityIcons } from '@expo/vector-icons';

import { HUDBackground } from './src/components/HUDBackground';
import { CentralOrb } from './src/components/CentralOrb';
import { ChatLog } from './src/components/ChatLog';
import { ControlBar } from './src/components/ControlBar';
import { Colors, Spacing, Typography } from './src/theme';
import { InputMode, Message, VoiceStatus } from './src/types';
import { chatRequest, voiceRequest, serverStatus } from './src/api/client';
import { useAudioRecorder, playAudioBase64 } from './src/hooks/useAudio';

let _msgId = 0;
const uid = () => String(++_msgId);

export default function App() {
  const [fontsLoaded] = useFonts({ ShareTechMono_400Regular });

  const [messages, setMessages]     = useState<Message[]>([]);
  const [status, setStatus]         = useState<VoiceStatus>('standby');
  const [isMuted, setIsMuted]       = useState(false);
  const [isSilent, setIsSilent]     = useState(false);
  const [inputMode, setInputMode]   = useState<InputMode>('voice');
  const [draftText, setDraftText]   = useState('');
  const [serverOnline, setServerOnline] = useState<boolean | null>(null);

  const { startRecording, stopRecording } = useAudioRecorder();

  // ── Server health check on mount ────────────────────────────────────────────
  useEffect(() => {
    serverStatus().then((res) => {
      setServerOnline(res !== null);
      if (res) {
        pushMessage('albedo',
          `Bridge online — ${res.llm_model} · Whisper ${res.whisper_model} (${res.whisper_device})`);
      } else {
        pushMessage('albedo',
          '[OFFLINE] Cannot reach server. Start server.py and verify Tailscale IP in src/api/client.ts');
      }
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pushMessage = useCallback((role: Message['role'], text: string) => {
    setMessages((prev) => [
      ...prev,
      { id: uid(), role, text, timestamp: Date.now() },
    ]);
  }, []);

  // ── Voice mic handler ────────────────────────────────────────────────────────
  const handleMicPress = useCallback(async () => {
    if (isMuted) return;
    if (status === 'processing' || status === 'speaking') return;

    // Pressing mic while keyboard is open: slide input away and return to voice standby
    if (inputMode === 'keyboard') {
      setInputMode('voice');
      setStatus('standby');
      return;
    }

    if (status === 'listening') {
      // ── Stop recording → send to server ──────────────────────────────────
      setStatus('processing');
      try {
        const audioUri = await stopRecording();
        if (!audioUri) throw new Error('No audio captured');

        const result = await voiceRequest(audioUri);

        pushMessage('user', result.transcript || '[voice input]');
        pushMessage('albedo', result.text);

        if (!isSilent && result.audio_b64) {
          setStatus('speaking');
          await playAudioBase64(result.audio_b64);
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Unknown error';
        pushMessage('albedo', `[BRIDGE ERROR] ${msg}`);
        // Ensure recording is cleaned up on error
        await stopRecording().catch(() => {});
      } finally {
        setStatus('standby');
      }

    } else {
      // ── Start recording ───────────────────────────────────────────────────
      try {
        await startRecording();
        setStatus('listening');
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Microphone unavailable';
        pushMessage('albedo', `[BRIDGE ERROR] ${msg}`);
        setStatus('standby');
      }
    }
  }, [status, isMuted, inputMode, isSilent, startRecording, stopRecording, pushMessage]);

  // ── Text chat handler ────────────────────────────────────────────────────────
  const handleSendText = useCallback(async () => {
    const text = draftText.trim();
    if (!text) return;

    pushMessage('user', text);
    setDraftText('');
    setStatus('processing');

    try {
      const result = await chatRequest(text);
      pushMessage('albedo', result.text);

      if (!isSilent && result.audio_b64) {
        setStatus('speaking');
        await playAudioBase64(result.audio_b64);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      pushMessage('albedo', `[BRIDGE ERROR] ${msg}`);
    } finally {
      setStatus('standby');
    }
  }, [draftText, isSilent, pushMessage]);

  // ── Auxiliary handlers ───────────────────────────────────────────────────────
  const handleMuteToggle = useCallback(() => {
    setIsMuted((m) => !m);
    if (status === 'listening') {
      stopRecording().catch(() => {});
      setStatus('standby');
    }
  }, [status, stopRecording]);

  const handleSilentToggle = useCallback(() => setIsSilent((s) => !s), []);

  const handleInputModeToggle = useCallback(() => {
    setInputMode((m) => (m === 'voice' ? 'keyboard' : 'voice'));
    if (status === 'listening') {
      stopRecording().catch(() => {});
      setStatus('standby');
    }
  }, [status, stopRecording]);

  // ── Loading splash ───────────────────────────────────────────────────────────
  if (!fontsLoaded) {
    return <View style={styles.loading} />;
  }

  return (
    <HUDBackground>
      <SafeAreaView style={styles.safe}>
        <StatusBar style="light" />
        <KeyboardAvoidingView
          style={styles.flex}
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        >

          {/* ── Header ──────────────────────────────────────────────── */}
          <View style={styles.header}>
            <Text style={styles.headerTitle}>ALBEDO</Text>

            <View style={styles.headerMeta}>
              <Text style={styles.headerSub}>SPARTAN-CLASS · HYBRID RAG</Text>

              {/* Server status indicator */}
              <View style={[
                styles.serverChip,
                serverOnline === true  && styles.serverChipOnline,
                serverOnline === false && styles.serverChipOffline,
              ]}>
                <MaterialCommunityIcons
                  name={serverOnline ? 'access-point' : 'access-point-off'}
                  size={10}
                  color={
                    serverOnline === true  ? Colors.cyan :
                    serverOnline === false ? Colors.danger :
                    Colors.textMuted
                  }
                />
                <Text style={[
                  styles.serverChipLabel,
                  serverOnline === true  && styles.serverChipLabelOnline,
                  serverOnline === false && styles.serverChipLabelOffline,
                ]}>
                  {serverOnline === null ? 'CONNECTING' : serverOnline ? 'BRIDGE' : 'OFFLINE'}
                </Text>
              </View>

              {/* Silent Protocol chip */}
              <TouchableOpacity
                onPress={handleSilentToggle}
                style={[styles.silentChip, isSilent && styles.silentChipActive]}
                activeOpacity={0.7}
                accessibilityLabel={isSilent ? 'Disable Silent Protocol' : 'Enable Silent Protocol'}
              >
                <MaterialCommunityIcons
                  name={isSilent ? 'volume-off' : 'volume-high'}
                  size={10}
                  color={isSilent ? Colors.cyan : Colors.textMuted}
                />
                <Text style={[styles.silentLabel, isSilent && styles.silentLabelActive]}>
                  {isSilent ? 'SILENT' : 'AUDIO'}
                </Text>
              </TouchableOpacity>
            </View>

            {/* Active silent protocol banner */}
            {isSilent && (
              <View style={styles.silentBanner}>
                <Text style={styles.silentBannerText}>◉  SILENT PROTOCOL ENGAGED</Text>
              </View>
            )}
          </View>

          {/* ── Central orb ─────────────────────────────────────────── */}
          <View style={styles.orbSection}>
            <CentralOrb status={status} />
          </View>

          {/* ── Chat log ─────────────────────────────────────────────── */}
          <View style={styles.logSection}>
            <ChatLog messages={messages} />
          </View>

          {/* ── Control bar ──────────────────────────────────────────── */}
          <ControlBar
            status={status}
            isMuted={isMuted}
            isSilent={isSilent}
            inputMode={inputMode}
            draftText={draftText}
            onMicPress={handleMicPress}
            onMuteToggle={handleMuteToggle}
            onSilentToggle={handleSilentToggle}
            onInputModeToggle={handleInputModeToggle}
            onDraftChange={setDraftText}
            onSendText={handleSendText}
          />

        </KeyboardAvoidingView>
      </SafeAreaView>
    </HUDBackground>
  );
}

const styles = StyleSheet.create({
  loading: {
    flex: 1,
    backgroundColor: Colors.bg,
  },
  safe: {
    flex: 1,
  },
  flex: {
    flex: 1,
  },
  header: {
    alignItems: 'center',
    paddingTop: Spacing.lg,
    paddingBottom: Spacing.sm,
    gap: Spacing.xs,
  },
  headerTitle: {
    fontFamily: Typography.fontMono,
    fontSize: Typography.sizes.xxl,
    color: Colors.cyan,
    letterSpacing: Typography.tracking.widest,
    textShadowColor: Colors.cyanGlowStrong,
    textShadowOffset: { width: 0, height: 0 },
    textShadowRadius: 12,
  },
  headerMeta: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
  },
  headerSub: {
    fontFamily: Typography.fontMono,
    fontSize: Typography.sizes.hud,
    color: Colors.textMuted,
    letterSpacing: Typography.tracking.wider,
  },
  // Server status chip
  serverChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    paddingHorizontal: Spacing.sm,
    paddingVertical: 3,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: 'rgba(10, 15, 44, 0.6)',
  },
  serverChipOnline: {
    borderColor: Colors.cyanDim,
    backgroundColor: 'rgba(0, 153, 187, 0.12)',
  },
  serverChipOffline: {
    borderColor: 'rgba(255, 58, 92, 0.4)',
    backgroundColor: 'rgba(255, 58, 92, 0.08)',
  },
  serverChipLabel: {
    fontFamily: Typography.fontMono,
    fontSize: 9,
    color: Colors.textMuted,
    letterSpacing: 2,
  },
  serverChipLabelOnline: {
    color: Colors.cyan,
  },
  serverChipLabelOffline: {
    color: Colors.danger,
  },
  // Silent Protocol chip
  silentChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    paddingHorizontal: Spacing.sm,
    paddingVertical: 3,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: 'rgba(10, 15, 44, 0.6)',
  },
  silentChipActive: {
    borderColor: Colors.cyanDim,
    backgroundColor: 'rgba(0, 153, 187, 0.15)',
  },
  silentLabel: {
    fontFamily: Typography.fontMono,
    fontSize: 9,
    color: Colors.textMuted,
    letterSpacing: 2,
  },
  silentLabelActive: {
    color: Colors.cyan,
  },
  silentBanner: {
    borderWidth: 1,
    borderColor: Colors.cyanDim,
    backgroundColor: 'rgba(0, 153, 187, 0.1)',
    paddingHorizontal: Spacing.md,
    paddingVertical: 4,
    borderRadius: 4,
    marginTop: Spacing.xs,
  },
  silentBannerText: {
    fontFamily: Typography.fontMono,
    fontSize: Typography.sizes.hud,
    color: Colors.cyanDim,
    letterSpacing: Typography.tracking.wide,
  },
  orbSection: {
    alignItems: 'center',
    paddingVertical: Spacing.xl,
  },
  logSection: {
    flex: 1,
  },
});
