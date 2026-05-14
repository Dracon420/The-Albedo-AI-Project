import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Colors, Radii, Spacing, Typography } from '../theme';
import { Message } from '../types';
import { AlbedoAvatar } from './AlbedoAvatar';

interface Props {
  message: Message;
}

function formatTime(ts: number): string {
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
}

export function ChatBubble({ message }: Props) {
  const isAlbedo = message.role === 'albedo';

  if (isAlbedo) {
    return (
      <View style={styles.rowAlbedo}>
        <AlbedoAvatar />
        <View style={styles.colAlbedo}>
          <View style={styles.headerRow}>
            <Text style={styles.senderLabel}>ALBEDO</Text>
            <Text style={styles.timestamp}>{formatTime(message.timestamp)}</Text>
          </View>
          <View style={styles.bubbleAlbedo}>
            <Text style={styles.textAlbedo}>{message.text}</Text>
          </View>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.rowUser}>
      <View style={styles.colUser}>
        <View style={styles.headerRowUser}>
          <Text style={styles.timestamp}>{formatTime(message.timestamp)}</Text>
          <Text style={styles.senderLabelUser}>OPERATOR</Text>
        </View>
        <View style={styles.bubbleUser}>
          <Text style={styles.textUser}>{message.text}</Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  rowAlbedo: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: Spacing.lg,
    paddingHorizontal: Spacing.lg,
  },
  rowUser: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    marginBottom: Spacing.lg,
    paddingHorizontal: Spacing.lg,
  },
  colAlbedo: {
    flex: 1,
  },
  colUser: {
    maxWidth: '80%',
    alignItems: 'flex-end',
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: Spacing.xs,
    gap: Spacing.sm,
  },
  headerRowUser: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: Spacing.xs,
    gap: Spacing.sm,
  },
  senderLabel: {
    fontFamily: Typography.fontMono,
    fontSize: Typography.sizes.hud,
    color: Colors.cyan,
    letterSpacing: Typography.tracking.wide,
  },
  senderLabelUser: {
    fontFamily: Typography.fontMono,
    fontSize: Typography.sizes.hud,
    color: Colors.textSecondary,
    letterSpacing: Typography.tracking.wide,
  },
  timestamp: {
    fontFamily: Typography.fontMono,
    fontSize: Typography.sizes.xs,
    color: Colors.textMuted,
  },
  bubbleAlbedo: {
    backgroundColor: Colors.bubbleAlbedo,
    borderWidth: 1,
    borderColor: Colors.bubbleBorderAlbedo,
    borderRadius: Radii.md,
    borderTopLeftRadius: 2,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
  },
  bubbleUser: {
    backgroundColor: Colors.bubbleUser,
    borderWidth: 1,
    borderColor: Colors.bubbleBorderUser,
    borderRadius: Radii.md,
    borderTopRightRadius: 2,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
  },
  textAlbedo: {
    fontFamily: Typography.fontMono,
    fontSize: Typography.sizes.md,
    color: Colors.textPrimary,
    lineHeight: 22,
  },
  textUser: {
    fontFamily: Typography.fontMono,
    fontSize: Typography.sizes.md,
    color: Colors.textSecondary,
    lineHeight: 22,
  },
});
