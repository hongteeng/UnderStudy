export interface Teacher {
  id: string;
  name: string;
}
export interface AskRequest {
  teacher: string;
  question: string;
}
export interface AskResponse {
  answer?: string;
  error?: string;
}
