with open("src/processors/csv_processor.py", "r") as f:
    content = f.read()

new_process_method = """    def process(self, file_path: str) -> Dict[str, Any]:
        \"\"\"
        Process a CSV file containing HTML question and explanation pairs.
        \"\"\"
        import tempfile
        import boto3
        from urllib.parse import urlparse
        import requests

        is_s3 = file_path.startswith("s3://")
        is_http = file_path.startswith("http://") or file_path.startswith("https://")
        
        if not is_s3 and not is_http and not os.path.exists(file_path):
            raise FileNotFoundError(f"CSV file not found: {file_path}")

        tmp_file = None
        try:
            if is_s3 or is_http:
                tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
                local_path = tmp_file.name
                
                if is_s3:
                    parsed = urlparse(file_path)
                    bucket = parsed.netloc
                    key = parsed.path.lstrip('/')
                    s3 = boto3.client('s3')
                    s3.download_file(bucket, key, local_path)
                else:
                    response = requests.get(file_path)
                    response.raise_for_status()
                    with open(local_path, "wb") as f:
                        f.write(response.content)
                
                process_path = local_path
            else:
                process_path = file_path

            # Read CSV
            try:
                df = pd.read_csv(process_path, encoding='utf-8')
            except UnicodeDecodeError:
                df = pd.read_csv(process_path, encoding='latin1')
                
            columns = list(df.columns)
            q_col = self._find_column(columns, self.question_col_hints)
            e_col = self._find_column(columns, self.explanation_col_hints)
            
            if not q_col:
                raise ValueError(f"Could not find a Question column in {file_path}. Available columns: {columns}")
            if not e_col:
                raise ValueError(f"Could not find an Explanation/Solution column in {file_path}. Available columns: {columns}")
                
            documents = []
            
            for idx, row in df.iterrows():
                raw_q = row[q_col]
                raw_e = row[e_col]
                
                if pd.isna(raw_q) and pd.isna(raw_e):
                    continue
                    
                clean_q = self._html_to_markdown(raw_q)
                clean_e = self._html_to_markdown(raw_e)
                
                combined_content = f"Question:\\n{clean_q}\\n\\nOfficial Solution/Explanation:\\n{clean_e}"
                
                documents.append({
                    "content": combined_content,
                    "source": os.path.basename(file_path),
                    "row_index": idx,
                    "content_type": "csv_qa_pair",
                    "timestamp": datetime.now().isoformat()
                })
                
            if tmp_file:
                try:
                    os.unlink(tmp_file.name)
                except:
                    pass

            return {
                "documents": documents,
                "source": os.path.basename(file_path),
                "total_rows_processed": len(documents),
                "processed_at": datetime.now().isoformat()
            }
            
        except Exception as e:
            if tmp_file:
                try:
                    os.unlink(tmp_file.name)
                except:
                    pass
            logger.exception("Failed to process CSV")
            raise RuntimeError(f"Error processing CSV {file_path}: {str(e)}")
"""

start_marker = "    def process(self, file_path: str) -> Dict[str, Any]:"
start_idx = content.find(start_marker)
if start_idx == -1:
    raise RuntimeError("Could not find CSVProcessor.process method signature")

next_def_idx = content.find("\n    def ", start_idx + len(start_marker))
if next_def_idx == -1:
    next_def_idx = len(content)

content = content[:start_idx] + new_process_method + content[next_def_idx:]

with open("src/processors/csv_processor.py", "w") as f:
    f.write(content)
