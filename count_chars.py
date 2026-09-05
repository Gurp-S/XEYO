import os
import re

def count_characters_in_files():
    total_chars = 0
    file_count = 0
    
    # 定义要统计的文件扩展名
    extensions = ['.ts', '.tsx', '.js', '.jsx', '.py', '.md', '.json', '.toml', '.bat']
    
    # 只统计纯前端和纯后端目录
    target_dirs = ['gui/', 'python/']
    
    # 排除环境相关文件
    exclude_patterns = ['test_', 'tests/', 'test', 'node_modules/', 'venv/', '.venv/', '__pycache__', '.git/', 'dist/', 'build/', 'coverage/', 'package-lock.json', 'yarn.lock']
    
    for target_dir in target_dirs:
        for root, dirs, files in os.walk(target_dir):
            # 过滤掉不需要的目录
            dirs[:] = [d for d in dirs if not any(d.startswith(pattern) for pattern in exclude_patterns)]
            
            # 过滤掉不需要的文件
            files = [f for f in files if not any(f.startswith(pattern) for pattern in exclude_patterns)]
            
            for file in files:
                if any(file.endswith(ext) for ext in extensions):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            total_chars += len(content)
                            file_count += 1
                    except Exception:
                        # 跳过无法读取的文件
                        pass
    
    return total_chars, file_count

if __name__ == "__main__":
    total_chars, file_count = count_characters_in_files()
    print(f"文件总数: {file_count:,}")
    print(f"总字数: {total_chars:,}")