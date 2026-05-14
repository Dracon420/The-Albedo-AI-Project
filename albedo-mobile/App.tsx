import React, { useCallback, useState } from 'react';
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

let _msgId = 0;
const uid = () => String(++_msgId);

export default function App() {
  const [fontsLoaded] = useFonts({ ShareTechMono_400Regular });

  const [messages, setMessages] = useState<Message[]>([]);
  const [status, setStatus] = useState<VoiceStatus>('standby');
  const [isMuted, setIsMuted] = useState(false);
  const [isSilent, setIsSilent] = useState(false);
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

    // Pressing mic while in keyboard mode: slide input away, return to voice
    if (inputMode === 'keyboard') {
      setInputMode('voice');
      setStatus('standby');
      return;
    }

    if (status === 'listening') {
      setStatus('processing');
      setTimeout(() => {
        pushMessage('user', '[voice input]');
        if (!isSilent) {
          pushMessage('albedo', 'Voice pipeline online. Connect server.py over Tailscale to process real queries.');
        } else {
          pushMessage('albedo', '[SILENT PROTOCOL] Response suppressed. Audio playback disabled.');
        }
        setStatus('standby');
      }, 1200);
    } else if (status === 'standby') {
      setStatus('listening');
    }
  }, [status, isMuted, inputMode, isSilent, pushMessage]);

  // ── Keyboard send ───────────────────────────────────────────────────────────
  const handleSendText = useCallback(() => {
    const text = draftText.trim();
    if (!text) return;
    pushMessage('user', text);
    setDraftText('');
    setStatus('processing');

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

  const handleSilentToggle = useCallback(() => {
    setIsSilent((s) => !s);
  }, []);

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

            <View style={styles.headerMeta}>
              <Text style={styles.headerSub}>SPARTAN-CLASS · HYBRID RAG</Text>

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
    gap: Spacing.md,
  },
  headerSub: {
    fontFamily: Typography.fontMono,
    fontSize: Typography.sizes.hud,
    color: Colors.textMuted,
    letterSpacing: Typography.tracking.wider,
  },
  silentChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
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
