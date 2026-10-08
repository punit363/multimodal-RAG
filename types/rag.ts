// types/rag.ts

export interface OriginalContent {
    raw_text: string;
    tables_html: string[];
    images_base64: string[];
  }
  
  export interface RetrievedChunk {
    chunk_id: number;
    enhanced_content: string;
    metadata: {
      original_content: OriginalContent;
    };
  }
  
  export interface QueryResponse {
    answer: string;
    sources: RetrievedChunk[];
  }
  
  export interface IngestResponse {
    status: string;
    message: string;
    filename: string;
  }
