import React, { useEffect, useRef } from 'react';
import { FlatList, StyleSheet, Text, View } from 'react-native';
import { Colors, Spacing, Typography } from '../theme';
import { Message } from '../types';
import { ChatBubble } from './ChatBubble';

interface Props {
  messages: Message[];
}

export function ChatLog({ messages }: Props) {
  const listRef = useRef<FlatList<Message>>(null);

  useEffect(() => {
    if (messages.length > 0) {
      listRef.current?.scrollToEnd({ animated: true });
    }
  }, [messages.length]);

  if (messages.length === 0) {
    return (
      <View style={styles.empty}>
        <Text style={styles.emptyLabel}>[ NO TRANSMISSIONS ]</Text>
        <Text style={styles.emptyHint}>Say &quot;Cortana&quot; to activate</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {/* HUD top border */}
      <View style={styles.divider}>
        <View style={styles.dividerLine} />
        <Text style={styles.dividerLabel}>COMM LOG</Text>
        <View style={styles.dividerLine} />
      </View>

      <FlatList
        ref={listRef}
        data={messages}
        keyExtractor={(m) => m.id}
        renderItem={({ item }) => <ChatBubble message={item} />}
        contentContainerStyle={styles.list}
        showsVerticalScrollIndicator={false}
        onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: false })}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  list: {
    paddingTop: Spacing.md,
    paddingBottom: Spacing.xl,
  },
  divider: {
    flexDirection: 'row',
    alignItems: 'center',
    marginHorizontal: Spacing.lg,
    marginBottom: Spacing.sm,
    gap: Spacing.sm,
  },
  dividerLine: {
    flex: 1,
    height: 1,
    backgroundColor: Colors.border,
  },
  dividerLabel: {
    fontFamily: Typography.fontMono,
    fontSize: Typography.sizes.hud,
    color: Colors.textMuted,
    letterSpacing: Typography.tracking.wider,
  },
  empty: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: Spacing.sm,
  },
  emptyLabel: {
    fontFamily: Typography.fontMono,
    fontSize: Typography.sizes.sm,
    color: Colors.textMuted,
    letterSpacing: Typography.tracking.wider,
  },
  emptyHint: {
    fontFamily: Typography.fontMono,
    fontSize: Typography.sizes.xs,
    color: Colors.textMuted,
    opacity: 0.5,
  },
});
