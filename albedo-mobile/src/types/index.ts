export type MessageRole = 'albedo' | 'user';

export interface Message {
  id: string;
  role: MessageRole;
  text: string;
  timestamp: number;
}

export type InputMode = 'voice' | 'keyboard';

export type VoiceStatus = 'standby' | 'listening' | 'processing' | 'speaking';

export interface VoiceState {
  status: VoiceStatus;
  isMicActive: boolean;
  isMuted: boolean;
  inputMode: InputMode;
}
