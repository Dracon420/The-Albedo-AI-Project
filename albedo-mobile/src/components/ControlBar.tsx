import React, { useEffect, useRef } from 'react';
import {
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import Animated, {
  Easing,
  interpolate,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { Colors, Radii, Spacing, Typography } from '../theme';
import { InputMode, VoiceStatus } from '../types';

interface Props {
  status: VoiceStatus;
  isMuted: boolean;
  isSilent: boolean;
  inputMode: InputMode;
  draftText: string;
  onMicPress: () => void;
  onMuteToggle: () => void;
  onSilentToggle: () => void;
  onInputModeToggle: () => void;
  onDraftChange: (text: string) => void;
  onSendText: () => void;
}

const STATUS_LABELS: Record<VoiceStatus, string> = {
  standby:    'STANDBY',
  listening:  'LISTENING...',
  processing: 'PROCESSING',
  speaking:   'TRANSMITTING',
};

const SLIDE_DURATION = 260;

export function ControlBar({
  status,
  isMuted,
  isSilent,
  inputMode,
  draftText,
  onMicPress,
  onMuteToggle,
  onSilentToggle,
  onInputModeToggle,
  onDraftChange,
  onSendText,
}: Props) {
  const inputRef = useRef<TextInput>(null);
  const slideProgress = useSharedValue(inputMode === 'keyboard' ? 1 : 0);

  // Animate whenever inputMode changes
  useEffect(() => {
    slideProgress.value = withTiming(inputMode === 'keyboard' ? 1 : 0, {
      duration: SLIDE_DURATION,
      easing: Easing.out(Easing.cubic),
    });

    // Auto-focus the text input once the slide-in animation is nearly done
    if (inputMode === 'keyboard') {
      const t = setTimeout(() => inputRef.current?.focus(), SLIDE_DURATION - 40);
      return () => clearTimeout(t);
    }
  }, [inputMode]);

  // Height collapses to 0 when voice; expands to 60 when keyboard
  const inputSlideStyle = useAnimatedStyle(() => ({
    height: interpolate(slideProgress.value, [0, 1], [0, 60]),
    opacity: interpolate(slideProgress.value, [0, 0.45, 1], [0, 0, 1]),
    overflow: 'hidden',
    marginBottom: interpolate(slideProgress.value, [0, 1], [0, Spacing.sm]),
  }));

  const isMicActive = status === 'listening';
  const isProcessing = status === 'processing' || status === 'speaking';

  const micColor = isMuted
    ? Colors.danger
    : isMicActive
    ? Colors.cyan
    : Colors.iconInactive;

  return (
    <View style={styles.container}>

      {/* ── Status row ──────────────────────────────────────────────── */}
      <View style={styles.statusRow}>
        <View style={styles.statusDot}>
          <View style={[
            styles.dot,
            isMicActive  && styles.dotListening,
            isProcessing && styles.dotProcessing,
          ]} />
        </View>
        <Text style={[styles.statusLabel, isMicActive && styles.statusLabelActive]}>
          {STATUS_LABELS[status]}
        </Text>
      </View>

      {/* ── Hairline separator ───────────────────────────────────────── */}
      <View style={styles.separator} />

      {/* ── Animated text input — slides in/out ─────────────────────── */}
      <Animated.View style={inputSlideStyle}>
        <View style={styles.inputRow}>
          <TextInput
            ref={inputRef}
            style={styles.textInput}
            value={draftText}
            onChangeText={onDraftChange}
            placeholder="ENTER COMMAND..."
            placeholderTextColor={Colors.textMuted}
            onSubmitEditing={onSendText}
            returnKeyType="send"
            multiline={false}
          />
          <Pressable
            onPress={onSendText}
            style={({ pressed }) => [styles.sendButton, pressed && styles.sendButtonPressed]}
            disabled={!draftText.trim()}
          >
            <MaterialCommunityIcons
              name="send"
              size={18}
              color={draftText.trim() ? Colors.cyan : Colors.iconInactive}
            />
          </Pressable>
        </View>
      </Animated.View>

      {/* ── Icon control row ─────────────────────────────────────────── */}
      <View style={styles.controlRow}>

        {/* Mute toggle */}
        <Pressable
          onPress={onMuteToggle}
          style={({ pressed }) => [
            styles.iconButton,
            isMuted && styles.iconButtonDanger,
            pressed && styles.iconButtonPressed,
          ]}
          accessibilityLabel={isMuted ? 'Unmute microphone' : 'Mute microphone'}
        >
          <MaterialCommunityIcons
            name={isMuted ? 'microphone-off' : 'microphone'}
            size={20}
            color={isMuted ? Colors.danger : Colors.iconInactive}
          />
        </Pressable>

        {/* Mic — primary action */}
        <Pressable
          onPress={onMicPress}
          style={({ pressed }) => [
            styles.micButton,
            isMicActive  && styles.micButtonListening,
            isProcessing && styles.micButtonProcessing,
            pressed      && styles.micButtonPressed,
          ]}
          accessibilityLabel={isMicActive ? 'Stop listening' : 'Activate voice input'}
        >
          <MaterialCommunityIcons
            name={isMicActive ? 'waveform' : 'microphone'}
            size={30}
            color={micColor}
          />
        </Pressable>

        {/* Keyboard toggle */}
        <Pressable
          onPress={onInputModeToggle}
          style={({ pressed }) => [
            styles.iconButton,
            inputMode === 'keyboard' && styles.iconButtonActive,
            pressed && styles.iconButtonPressed,
          ]}
          accessibilityLabel="Toggle keyboard input"
        >
          <MaterialCommunityIcons
            name={inputMode === 'keyboard' ? 'keyboard-off' : 'keyboard'}
            size={20}
            color={inputMode === 'keyboard' ? Colors.cyan : Colors.iconInactive}
          />
        </Pressable>

      </View>

      {/* ── Silent Protocol status line ──────────────────────────────── */}
      {isSilent && (
        <View style={styles.silentStatusLine}>
          <MaterialCommunityIcons name="volume-off" size={10} color={Colors.cyanDim} />
          <Text style={styles.silentStatusText}>SILENT PROTOCOL  —  AUDIO SUPPRESSED</Text>
        </View>
      )}

    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingBottom: Spacing.xxl,
    paddingHorizontal: Spacing.xl,
    paddingTop: Spacing.md,
    borderTopWidth: 1,
    borderTopColor: Colors.border,
    backgroundColor: 'rgba(8, 12, 36, 0.92)',
    gap: Spacing.sm,
  },

  // Status row
  statusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: Spacing.sm,
  },
  statusDot: {
    width: 16,
    alignItems: 'center',
  },
  dot: {
    width: 5,
    height: 5,
    borderRadius: 99,
    backgroundColor: Colors.textMuted,
  },
  dotListening: {
    backgroundColor: Colors.cyan,
    shadowColor: Colors.cyan,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.9,
    shadowRadius: 5,
    elevation: 4,
  },
  dotProcessing: {
    backgroundColor: Colors.cyanDim,
  },
  statusLabel: {
    fontFamily: Typography.fontMono,
    fontSize: Typography.sizes.hud,
    color: Colors.textMuted,
    letterSpacing: Typography.tracking.widest,
  },
  statusLabelActive: {
    color: Colors.cyan,
  },

  separator: {
    height: 1,
    backgroundColor: Colors.border,
  },

  // Animated input row
  inputRow: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(0, 245, 255, 0.04)',
    borderWidth: 1,
    borderColor: Colors.borderActive,
    borderRadius: Radii.sm,
    paddingHorizontal: Spacing.md,
    gap: Spacing.sm,
    marginBottom: 2,
  },
  textInput: {
    flex: 1,
    fontFamily: Typography.fontMono,
    fontSize: Typography.sizes.md,
    color: Colors.textPrimary,
    height: 44,
    paddingVertical: 0,
    letterSpacing: 1,
  },
  sendButton: {
    padding: Spacing.xs,
  },
  sendButtonPressed: {
    opacity: 0.45,
  },

  // Control row
  controlRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: Spacing.sm,
  },
  iconButton: {
    width: 52,
    height: 52,
    borderRadius: Radii.full,
    borderWidth: 1,
    borderColor: Colors.border,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(15, 25, 70, 0.55)',
  },
  iconButtonActive: {
    borderColor: Colors.borderActive,
    backgroundColor: 'rgba(0, 245, 255, 0.08)',
  },
  iconButtonDanger: {
    borderColor: 'rgba(255, 58, 92, 0.4)',
    backgroundColor: 'rgba(255, 58, 92, 0.08)',
  },
  iconButtonPressed: {
    opacity: 0.55,
  },

  // Mic button
  micButton: {
    width: 76,
    height: 76,
    borderRadius: Radii.full,
    borderWidth: 1.5,
    borderColor: Colors.blueDim,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(10, 40, 110, 0.65)',
  },
  micButtonListening: {
    borderColor: Colors.cyan,
    backgroundColor: 'rgba(0, 60, 120, 0.85)',
    shadowColor: Colors.cyan,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.65,
    shadowRadius: 18,
    elevation: 14,
  },
  micButtonProcessing: {
    borderColor: Colors.cyanDim,
    backgroundColor: 'rgba(0, 40, 90, 0.85)',
  },
  micButtonPressed: {
    opacity: 0.65,
  },

  // Silent Protocol footer
  silentStatusLine: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingTop: 2,
  },
  silentStatusText: {
    fontFamily: Typography.fontMono,
    fontSize: 9,
    color: Colors.cyanDim,
    letterSpacing: Typography.tracking.wide,
  },
});
