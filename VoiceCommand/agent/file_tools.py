"""
파일 작업 유틸리티 (File Tools)
이름 변경, 병합, 정리, CSV/JSON 분석 및 보고서 생성을 지원합니다.
"""
import os
import shutil
import json
import csv
import logging
import re
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


def detect_file_set(folder_path: str, extensions: Optional[List[str]] = None) -> Dict[str, Any]:
    """폴더 내 파일 세트를 스캔하고 확장자별/패턴별 통계를 반환합니다."""
    try:
        if not os.path.isdir(folder_path):
            return {"error": "디렉터리가 아닙니다."}
        normalized_exts = {ext.lower().lstrip(".") for ext in (extensions or []) if ext}
        files = []
        by_extension: Dict[str, int] = {}
        for name in sorted(os.listdir(folder_path)):
            path = os.path.join(folder_path, name)
            if not os.path.isfile(path):
                continue
            ext = os.path.splitext(name)[1].lstrip(".").lower() or "others"
            if normalized_exts and ext not in normalized_exts:
                continue
            files.append(name)
            by_extension[ext] = by_extension.get(ext, 0) + 1
        return {
            "file_count": len(files),
            "extensions": by_extension,
            "sample_files": files[:20],
        }
    except Exception as e:
        logger.error(f"detect_file_set 오류: {e}")
        return {"error": str(e)}


def batch_rename_files(folder_path: str, rename_rule: str, replacement: str = "", dry_run: bool = False) -> Dict[str, Any]:
    """정규식 기반 파일 이름 일괄 변경."""
    try:
        if not os.path.isdir(folder_path):
            return {"error": "디렉터리가 아닙니다."}
        pattern = re.compile(rename_rule)
        results = []
        for name in sorted(os.listdir(folder_path)):
            path = os.path.join(folder_path, name)
            if not os.path.isfile(path):
                continue
            new_name = pattern.sub(replacement, name)
            if not new_name or new_name == name:
                continue
            result_item = {"old_name": name, "new_name": new_name}
            if not dry_run:
                os.rename(path, os.path.join(folder_path, new_name))
            results.append(result_item)
        return {"renamed_count": len(results), "changes": results}
    except Exception as e:
        logger.error(f"batch_rename_files 오류: {e}")
        return {"error": str(e)}

def rename_file(old_path: str, new_name: str) -> str:
    """파일 또는 디렉터리 이름 변경.
    
    Args:
        old_path: 원래 경로
        new_name: 새로운 이름 (경로 제외)
    """
    try:
        dir_name = os.path.dirname(old_path)
        new_path = os.path.join(dir_name, new_name)
        os.rename(old_path, new_path)
        return new_path
    except Exception as e:
        logger.error(f"rename_file 오류: {e}")
        return f"오류: {e}"

def merge_text_files(file_paths: List[str], output_path: str) -> str:
    """여러 텍스트 파일을 하나로 병합.
    
    Args:
        file_paths: 병합할 파일 경로 목록
        output_path: 저장할 결과 파일 경로
    """
    try:
        with open(output_path, 'w', encoding='utf-8') as outfile:
            for fname in file_paths:
                if not os.path.exists(fname):
                    continue
                with open(fname, 'r', encoding='utf-8', errors='ignore') as infile:
                    outfile.write(f"\n--- 원본 파일: {os.path.basename(fname)} ---\n")
                    outfile.write(infile.read())
                    outfile.write("\n")
        return output_path
    except Exception as e:
        logger.error(f"merge_text_files 오류: {e}")
        return f"오류: {e}"

def organize_folder_by_extension(folder_path: str) -> Dict[str, int]:
    """폴더 내 파일들을 확장자별 서브 폴더로 정리.
    
    Args:
        folder_path: 대상 폴더 경로
    Returns:
        정리된 파일 통계
    """
    try:
        stats = {}
        if not os.path.isdir(folder_path):
            return {"error": "디렉터리가 아닙니다."}
            
        for filename in os.listdir(folder_path):
            filepath = os.path.join(folder_path, filename)
            if os.path.isdir(filepath):
                continue
                
            ext = filename.split('.')[-1].lower() if '.' in filename else 'others'
            # 확장자가 너무 길거나 이상한 경우 처리
            if len(ext) > 10:
                ext = 'others'
                
            target_dir = os.path.join(folder_path, ext)
            os.makedirs(target_dir, exist_ok=True)
            
            # 파일 이동 (중복 시 이름 변경)
            dest_path = os.path.join(target_dir, filename)
            if os.path.exists(dest_path):
                base, extension = os.path.splitext(filename)
                dest_path = os.path.join(target_dir, f"{base}_{int(datetime.now().timestamp())}{extension}")
                
            shutil.move(filepath, dest_path)
            stats[ext] = stats.get(ext, 0) + 1
            
        return stats
    except Exception as e:
        logger.error(f"organize_folder 오류: {e}")
        return {"error": str(e)}

def analyze_data_file(file_path: str) -> Dict[str, Any]:
    """CSV 또는 JSON 파일의 구조와 통계를 분석.
    
    Args:
        file_path: 데이터 파일 경로
    """
    try:
        if not os.path.exists(file_path):
            return {"error": "파일이 존재하지 않습니다."}
            
        ext = file_path.split('.')[-1].lower()
        if ext == 'json':
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    sample_keys = list(data[0].keys()) if data and isinstance(data[0], dict) else []
                    column_samples = {}
                    for row in data[:5]:
                        if isinstance(row, dict):
                            for key, value in row.items():
                                column_samples.setdefault(str(key), []).append(value)
                    return {
                        "format": "json_array",
                        "row_count": len(data),
                        "sample_keys": sample_keys,
                        "column_samples": {key: values[:3] for key, values in column_samples.items()},
                    }
                return {
                    "format": "json_object",
                    "keys": list(data.keys())
                }
        elif ext == 'csv':
            with open(file_path, 'r', encoding='utf-8') as f:
                # 인코딩 문제 대응을 위해 시도
                try:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                    numeric_columns = _summarize_numeric_columns(rows, reader.fieldnames or [])
                    return {
                        "format": "csv",
                        "row_count": len(rows),
                        "columns": reader.fieldnames,
                        "column_samples": _sample_columns(rows, reader.fieldnames or []),
                        "numeric_summary": numeric_columns,
                    }
                except Exception:
                    f.seek(0)
                    content = f.read(4096)
                    return {
                        "format": "csv_raw",
                        "lines": len(content.splitlines()),
                        "note": "상세 파싱 실패"
                    }
        return {"error": "지원하지 않는 형식입니다."}
    except Exception as e:
        logger.error(f"analyze_data_file 오류: {e}")
        return {"error": str(e)}

def generate_markdown_report(content: str, output_path: str, title: str = "분석 보고서") -> str:
    """마크다운 형식의 보고서 생성.
    
    Args:
        content: 보고서 본문 (마크다운)
        output_path: 저장 경로
        title: 보고서 제목
    """
    try:
        full_content = f"# {title}\n\n"
        full_content += f"*생성 일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n"
        full_content += "---\n\n"
        full_content += content
        
        # 폴더 생성 보장
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(full_content)
        return output_path
    except Exception as e:
        logger.error(f"generate_markdown_report 오류: {e}")
        return f"오류: {e}"


def _sample_columns(rows: List[Dict[str, Any]], columns: List[str], limit: int = 3) -> Dict[str, List[Any]]:
    samples: Dict[str, List[Any]] = {}
    for column in columns:
        values = []
        for row in rows[: max(limit * 2, limit)]:
            value = row.get(column)
            if value in (None, ""):
                continue
            values.append(value)
            if len(values) >= limit:
                break
        if values:
            samples[column] = values
    return samples


def _summarize_numeric_columns(rows: List[Dict[str, Any]], columns: List[str]) -> Dict[str, Dict[str, Any]]:
    summary: Dict[str, Dict[str, Any]] = {}
    for column in columns:
        numeric_values = []
        for row in rows:
            raw = row.get(column)
            if raw in (None, ""):
                continue
            try:
                numeric_values.append(float(raw))
            except (TypeError, ValueError):
                numeric_values = []
                break
        if len(numeric_values) < 2:
            continue
        avg = sum(numeric_values) / len(numeric_values)
        variance = sum((value - avg) ** 2 for value in numeric_values) / len(numeric_values)
        std_dev = variance ** 0.5
        outliers = [value for value in numeric_values if std_dev and abs(value - avg) > std_dev * 2]
        summary[column] = {
            "min": min(numeric_values),
            "max": max(numeric_values),
            "mean": round(avg, 4),
            "outlier_count": len(outliers),
            "sample_outliers": outliers[:5],
        }
    return summary
