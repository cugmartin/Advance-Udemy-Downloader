"""
从 HTML 文件上传文章到 WordPress
读取转换后的 HTML 文件（使用 md_to_html_converter.py 生成），上传到 WordPress 并保存为草稿
"""

import os
import sys
import re
import tempfile
import importlib.util
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.wordpress_client import WordPressClient

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    print("错误: 需要安装 BeautifulSoup4")
    print("请运行: pip install beautifulsoup4")
    sys.exit(1)

# 加载环境变量
load_dotenv()

# 动态加载 Markdown → HTML 转换器
md_converter_spec = importlib.util.spec_from_file_location(
    "md_to_html_converter",
    project_root / "scripts" / "md_to_html_converter.py",
)
md_converter_module = importlib.util.module_from_spec(md_converter_spec)
md_converter_spec.loader.exec_module(md_converter_module)
convert_markdown_to_html = md_converter_module.convert_markdown_to_html


def extract_title_from_html(html_content, fallback_name: str = None):
    """从 HTML 中提取标题"""
    soup = BeautifulSoup(html_content, 'html.parser')
    title_tag = soup.find('title')
    if title_tag:
        title_text = title_tag.get_text().strip()
        normalized = title_text.lower()
        if title_text and normalized not in {"untitled document", "untitled"}:
            return title_text, "title tag"
    
    h1_tag = soup.find('h1')
    if h1_tag:
        # 提取纯文本，移除所有 HTML 标签
        title_text = h1_tag.get_text().strip()
        return title_text, "h1"

    for level in range(2, 7):
        tag = soup.find(f'h{level}')
        if tag:
            text = tag.get_text().strip()
            if text:
                return text, f'h{level}'

    if fallback_name:
        friendly = fallback_name.replace('_', ' ').replace('-', ' ').strip()
        return friendly or "Untitled Post", "filename"

    return "Untitled Post", "default"
    
    return "Untitled Post"


def extract_content_from_html(html_content):
    """从 HTML 中提取内容部分（content div）"""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 提取 content div 的内容
    content_div = soup.find('div', class_=lambda x: x and 'content' in x.lower().split() if x else False)
    if content_div:
        return str(content_div)
    
    # 如果没有 content div，提取 body 内容（排除 container 和 header）
    body = soup.find('body')
    if body:
        # 移除 container 和 header div
        for div in body.find_all('div', class_=lambda x: x and any(
            cls in x.lower().split() for cls in ['container', 'header']
        ) if x else False):
            div.decompose()
        return str(body)
    
    return str(soup)


def upload_html_to_wordpress(html_file_path, status='draft'):
    """
    读取 HTML 文件并上传到 WordPress
    
    Args:
        html_file_path: HTML 文件路径
        status: 文章状态，默认为 'draft'（草稿）
    
    Returns:
        WordPress 文章对象，如果失败则返回 None
    """
    input_path = Path(html_file_path)
    temp_html_path: Optional[Path] = None

    # 如果传入 Markdown，先转换为 HTML
    if input_path.suffix.lower() == ".md":
        if not input_path.exists():
            print(f"错误: Markdown 文件 {html_file_path} 不存在")
            return None
        print(f"检测到 Markdown 文件，先转换为 HTML: {html_file_path}")
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".html")
        temp_file.close()
        temp_html_path = Path(temp_file.name)
        try:
            convert_markdown_to_html(
                md_file_path=str(input_path),
                output_file_path=str(temp_html_path),
                inline_styles=True,
            )
        except Exception as convert_err:
            print(f"错误: Markdown 转换失败: {convert_err}")
            if temp_html_path.exists():
                temp_html_path.unlink()
            return None
        html_path = temp_html_path
    else:
        html_path = input_path

    # 检查文件是否存在
    if not html_path.exists():
        print(f"错误: 文件 {html_path} 不存在")
        if temp_html_path and temp_html_path.exists():
            temp_html_path.unlink()
        return None
    
    # 读取 HTML 文件
    print(f"正在读取文件: {html_path}")
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
    except FileNotFoundError:
        print(f"错误: 文件 {html_path} 不存在")
        if temp_html_path and temp_html_path.exists():
            temp_html_path.unlink()
        return None
    except Exception as e:
        print(f"错误: 读取文件时出现问题: {e}")
        if temp_html_path and temp_html_path.exists():
            temp_html_path.unlink()
        return None
    
    # 提取标题
    print("正在提取标题...")
    title, source = extract_title_from_html(html_content, fallback_name=html_path.stem)
    print(f"提取的标题 ({source}): {title}")
    
    # 提取内容
    print("正在提取 HTML 内容...")
    content = extract_content_from_html(html_content)
    
    if not content:
        print("警告: 未能提取到内容")
        return None
    
    print(f"内容长度: {len(content)} 字符")
    
    # 从环境变量读取配置
    wordpress_url = os.getenv('WORDPRESS_URL')
    username = os.getenv('WORDPRESS_USERNAME')
    app_password = os.getenv('WORDPRESS_APP_PASSWORD')
    
    if not all([wordpress_url, username, app_password]):
        print("错误: 请确保 .env 文件中配置了以下变量：")
        print("  - WORDPRESS_URL")
        print("  - WORDPRESS_USERNAME")
        print("  - WORDPRESS_APP_PASSWORD")
        return None
    
    # 初始化客户端
    print("\n正在连接到 WordPress...")
    try:
        client = WordPressClient(
            wordpress_url=wordpress_url,
            username=username,
            app_password=app_password,
            disable_proxy=False
        )
    except Exception as e:
        print(f"错误: 连接 WordPress 时出错: {e}")
        return None
    
    # 上传文章
    print(f"\n正在创建文章（状态: {status}，使用内联样式）...")
    try:
        post = client.create_post(
            title=title,
            content=content,
            status=status
        )
        
        print(f"\n✓ 文章创建成功！")
        print(f"  文章 ID: {post['id']}")
        print(f"  文章标题: {post['title']['rendered']}")
        print(f"  文章状态: {post['status']}")
        if 'link' in post:
            print(f"  文章链接: {post['link']}")
        
        print("\n提示:")
        print("  - HTML 文件应使用内联样式，避免被 WordPress 过滤")
        print("  - 如果某些样式仍然缺失，可能是 WordPress 主题覆盖了部分样式")
        print("  - 建议在 WordPress 编辑器中预览效果")
        
        return post
        
    except ValueError as e:
        print(f"\n✗ API 错误: {e}")
        return None
    except Exception as e:
        print(f"\n✗ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        if temp_html_path and temp_html_path.exists():
            try:
                temp_html_path.unlink()
            except OSError:
                pass


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='从 HTML 文件上传文章到 WordPress',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python upload_md_to_wordpress.py article.html
  python upload_md_to_wordpress.py article.html --status publish
  python upload_md_to_wordpress.py article.html --status pending
        """
    )
    parser.add_argument('html_file', help='输入的 HTML 文件路径')
    parser.add_argument('--status', default='draft',
                       choices=['draft', 'publish', 'pending', 'private'],
                       help='文章状态（默认: draft）')
    
    args = parser.parse_args()
    
    # 检查文件是否存在
    if not Path(args.html_file).exists():
        print(f"错误: 文件 {args.html_file} 不存在")
        sys.exit(1)
    
    # 执行上传
    result = upload_html_to_wordpress(
        args.html_file,
        status=args.status
    )
    
    if result:
        print("\n✓ 完成！")
        sys.exit(0)
    else:
        print("\n✗ 上传失败")
        sys.exit(1)


if __name__ == '__main__':
    main()
