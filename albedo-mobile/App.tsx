import React, { useCallback, useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  SafeAreaView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useFonts, ShareTechMono_400Regular } from '@expo-google-fonts/share-tech-mono';

import { HUDBackground } from './src/components/HUDBackground';
import { CentralOrb } from './src/components/CentralOrb';
import { ChatLog } from './src/components/ChatLog';
import { ControlBar } from './src/components/ControlBar';
import { Colors, Spacing, Typography } from './src/theme';
import { InputMode, Message, VoiceStatus } from './src/types';

let _msgId = 0;
const uid = () => String(++_msgId);

export default function App() {
  const [fontsLoaded] = useFonts({ ShareTechMono_400Regular });

  const [messages, setMessages] = useState<Message[]>([]);
  const [status, setStatus] = useState<VoiceStatus>('standby');
  const [isMuted, setIsMuted] = useState(false);
  const [inputMode, setInputMode] = useState<InputMode>('voice');
  const [draftText, setDraftText] = useState('');

  const pushMessage = useCallback((role: Message['role'], text: string) => {
    setMessages((prev) => [
      ...prev,
      { id: uid(), role, text, timestamp: Date.now() },
    ]);
  }, []);

  // ── Voice mic toggle ────────────────────────────────────────────────────────
  const handleMicPress = useCallback(() => {
    if (isMuted) return;

    if (status === 'listening') {
      // Stop recording — in production this triggers STT + pipeline
      setStatus('processing');
      setTimeout(() => {
        pushMessage('user', '[voice input]');
        pushMessage('albedo', 'Voice pipeline is online. Connect server.py over Tailscale to process real queries.');
        setStatus('standby');
      }, 1200);
    } else if (status === 'standby') {
      setStatus('listening');
    }
  }, [status, isMuted, pushMessage]);

  // ── Keyboard send ───────────────────────────────────────────────────────────
  const handleSendText = useCallback(() => {
    const text = draftText.trim();
    if (!text) return;
    pushMessage('user', text);
    setDraftText('');
    setStatus('processing');

    // Stub response — replace with fetch() to /api/chat on your Tailscale IP
    setTimeout(() => {
      pushMessage(
        'albedo',
        `Received: "${text}". Connect to server.py at http://<tailscale-ip>:8000/api/chat for live responses.`,
      );
      setStatus('standby');
    }, 900);
  }, [draftText, pushMessage]);

  const handleMuteToggle = useCallback(() => {
    setIsMuted((m) => !m);
    if (status === 'listening') setStatus('standby');
  }, [status]);

  const handleInputModeToggle = useCallback(() => {
    setInputMode((m) => (m === 'voice' ? 'keyboard' : 'voice'));
    if (status === 'listening') setStatus('standby');
  }, [status]);

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
            <Text style={styles.headerSub}>SPARTAN-CLASS · HYBRID RAG</Text>
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
            inputMode={inputMode}
            draftText={draftText}
            onMicPress={handleMicPress}
            onMuteToggle={handleMuteToggle}
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
  },
  headerSub: {
    fontFamily: Typography.fontMono,
    fontSize: Typography.sizes.hud,
    color: Colors.textMuted,
    letterSpacing: Typography.tracking.wider,
  },
  orbSection: {
    alignItems: 'center',
    paddingVertical: Spacing.xl,
  },
  logSection: {
    flex: 1,
  },
});
