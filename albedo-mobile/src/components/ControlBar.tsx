import React from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { Colors, Radii, Spacing, Typography } from '../theme';
import { InputMode, VoiceStatus } from '../types';

interface Props {
  status: VoiceStatus;
  isMuted: boolean;
  inputMode: InputMode;
  draftText: string;
  onMicPress: () => void;
  onMuteToggle: () => void;
  onInputModeToggle: () => void;
  onDraftChange: (text: string) => void;
  onSendText: () => void;
}

const STATUS_LABELS: Record<VoiceStatus, string> = {
  standby: 'STANDBY',
  listening: 'LISTENING...',
  processing: 'PROCESSING',
  speaking: 'TRANSMITTING',
};

export function ControlBar({
  status,
  isMuted,
  inputMode,
  draftText,
  onMicPress,
  onMuteToggle,
  onInputModeToggle,
  onDraftChange,
  onSendText,
}: Props) {
  const isMicActive = status === 'listening';
  const micColor = isMuted
    ? Colors.danger
    : isMicActive
    ? Colors.cyan
    : Colors.iconInactive;

  return (
    <View style={styles.container}>
      {/* Status label */}
      <Text
        style={[
          styles.statusLabel,
          isMicActive && styles.statusLabelActive,
        ]}
      >
        {STATUS_LABELS[status]}
      </Text>

      {/* Separator */}
      <View style={styles.separator} />

      {/* Keyboard input row — shown when inputMode === 'keyboard' */}
      {inputMode === 'keyboard' && (
        <View style={styles.inputRow}>
          <TextInput
            style={styles.textInput}
            value={draftText}
            onChangeText={onDraftChange}
            placeholder="Enter command..."
            placeholderTextColor={Colors.textMuted}
            onSubmitEditing={onSendText}
            returnKeyType="send"
            multiline={false}
            autoFocus
          />
          <Pressable
            onPress={onSendText}
            style={({ pressed }) => [
              styles.sendButton,
              pressed && styles.sendButtonPressed,
            ]}
            disabled={!draftText.trim()}
          >
            <MaterialCommunityIcons
              name="send"
              size={18}
              color={draftText.trim() ? Colors.cyan : Colors.iconInactive}
            />
          </Pressable>
        </View>
      )}

      {/* Icon control row */}
      <View style={styles.controlRow}>
        {/* Mute toggle */}
        <Pressable
          onPress={onMuteToggle}
          style={({ pressed }) => [styles.iconButton, pressed && styles.iconButtonPressed]}
          accessibilityLabel={isMuted ? 'Unmute' : 'Mute'}
        >
          <MaterialCommunityIcons
            name={isMuted ? 'volume-off' : 'volume-high'}
            size={22}
            color={isMuted ? Colors.danger : Colors.iconInactive}
          />
        </Pressable>

        {/* Mic — primary action */}
        <Pressable
          onPress={onMicPress}
          style={({ pressed }) => [
            styles.micButton,
            isMicActive && styles.micButtonActive,
            pressed && styles.micButtonPressed,
          ]}
          accessibilityLabel={isMicActive ? 'Stop listening' : 'Start listening'}
        >
          <MaterialCommunityIcons
            name={isMuted ? 'microphone-off' : 'microphone'}
            size={28}
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
            name="keyboard"
            size={22}
            color={inputMode === 'keyboard' ? Colors.cyan : Colors.iconInactive}
          />
        </Pressable>
      </View>
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
    backgroundColor: 'rgba(10, 15, 44, 0.85)',
    gap: Spacing.md,
  },
  statusLabel: {
    fontFamily: Typography.fontMono,
    fontSize: Typography.sizes.hud,
    color: Colors.textMuted,
    textAlign: 'center',
    letterSpacing: Typography.tracking.widest,
  },
  statusLabelActive: {
    color: Colors.cyan,
  },
  separator: {
    height: 1,
    backgroundColor: Colors.border,
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Colors.bgSurface,
    borderWidth: 1,
    borderColor: Colors.borderActive,
    borderRadius: Radii.sm,
    paddingHorizontal: Spacing.md,
    gap: Spacing.sm,
  },
  textInput: {
    flex: 1,
    fontFamily: Typography.fontMono,
    fontSize: Typography.sizes.md,
    color: Colors.textPrimary,
    height: 44,
    paddingVertical: 0,
  },
  sendButton: {
    padding: Spacing.xs,
  },
  sendButtonPressed: {
    opacity: 0.5,
  },
  controlRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  iconButton: {
    width: 52,
    height: 52,
    borderRadius: Radii.full,
    borderWidth: 1,
    borderColor: Colors.border,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(15, 25, 70, 0.6)',
  },
  iconButtonActive: {
    borderColor: Colors.borderActive,
    backgroundColor: 'rgba(0, 60, 100, 0.5)',
  },
  iconButtonPressed: {
    opacity: 0.6,
  },
  micButton: {
    width: 72,
    height: 72,
    borderRadius: Radii.full,
    borderWidth: 1.5,
    borderColor: Colors.blueDim,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(10, 40, 100, 0.7)',
  },
  micButtonActive: {
    borderColor: Colors.cyan,
    backgroundColor: 'rgba(0, 60, 120, 0.85)',
    shadowColor: Colors.cyan,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.6,
    shadowRadius: 14,
    elevation: 12,
  },
  micButtonPressed: {
    opacity: 0.7,
  },
});
