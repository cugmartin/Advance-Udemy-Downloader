"""
将 Markdown 文件发布到 WordPress 的完整流程脚本

功能：
    1. 上传 Markdown 中的图片到 WordPress 媒体库并更新链接
    2. 将 Markdown 转换为 HTML（带内联样式）
    3. 上传 HTML 到 WordPress

使用方法：
    python scripts/publish_markdown_to_wordpress.py <markdown文件路径> [选项]

示例：
    # 基本用法（保存为草稿）
    python scripts/publish_markdown_to_wordpress.py examples/test222_zh.md

    # 直接发布
    python scripts/publish_markdown_to_wordpress.py examples/test222_zh.md --status publish

    # 跳过图片上传（如果图片已经上传过）
    python scripts/publish_markdown_to_wordpress.py examples/test222_zh.md --skip-images

    # 试运行模式（仅显示将要处理的图片，不实际上传）
    python scripts/publish_markdown_to_wordpress.py examples/test222_zh.md --dry-run

环境变量：
    需要在 .env 文件中配置：
    - WORDPRESS_URL: WordPress 站点 URL
    - WORDPRESS_USERNAME: WordPress 用户名
    - WORDPRESS_APP_PASSWORD: WordPress 应用密码
"""

import sys
import os
import argparse
import tempfile
import shutil
from pathlib import Path
from dotenv import load_dotenv

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.wordpress_client import WordPressClient

# 导入其他脚本的函数（使用 importlib 直接从文件导入）
import importlib.util

# 导入 upload_images_to_wordpress 模块
upload_images_spec = importlib.util.spec_from_file_location(
    "upload_images_to_wordpress",
    project_root / "scripts" / "upload_images_to_wordpress.py"
)
upload_images_module = importlib.util.module_from_spec(upload_images_spec)
upload_images_spec.loader.exec_module(upload_images_module)
upload_images_and_update_markdown = upload_images_module.upload_images_and_update_markdown
extract_image_links = upload_images_module.extract_image_links

# 导入 md_to_html_converter 模块
md_to_html_spec = importlib.util.spec_from_file_location(
    "md_to_html_converter",
    project_root / "scripts" / "md_to_html_converter.py"
)
md_to_html_module = importlib.util.module_from_spec(md_to_html_spec)
md_to_html_spec.loader.exec_module(md_to_html_module)
convert_markdown_to_html = md_to_html_module.convert_markdown_to_html

# 导入 upload_html_to_wordpress 模块
upload_html_spec = importlib.util.spec_from_file_location(
    "upload_html_to_wordpress",
    project_root / "scripts" / "upload_html_to_wordpress.py"
)
upload_html_module = importlib.util.module_from_spec(upload_html_spec)
upload_html_spec.loader.exec_module(upload_html_module)
upload_html_to_wordpress = upload_html_module.upload_html_to_wordpress


def publish_markdown_to_wordpress(
    markdown_file: str,
    status: str = 'draft',
    skip_images: bool = False,
    dry_run: bool = False,
    keep_temp_files: bool = False
) -> dict:
    """
    将 Markdown 文件发布到 WordPress 的完整流程
    
    Args:
        markdown_file: 输入的 Markdown 文件路径
        status: 文章状态，默认为 'draft'（草稿），可选 'publish', 'pending', 'private'
        skip_images: 是否跳过图片上传步骤
        dry_run: 是否为试运行模式（仅显示将要处理的图片，不实际上传）
        keep_temp_files: 是否保留临时文件（用于调试）
    
    Returns:
        包含处理结果的字典
    """
    markdown_path = Path(markdown_file)
    
    if not markdown_path.exists():
        raise FileNotFoundError(f"文件不存在: {markdown_file}")
    
    # 加载环境变量
    load_dotenv()
    
    wordpress_url = os.getenv('WORDPRESS_URL')
    wordpress_username = os.getenv('WORDPRESS_USERNAME')
    wordpress_password = os.getenv('WORDPRESS_APP_PASSWORD')
    
    if not all([wordpress_url, wordpress_username, wordpress_password]):
        raise ValueError(
            "请在 .env 文件中配置以下环境变量：\n"
            "  - WORDPRESS_URL\n"
            "  - WORDPRESS_USERNAME\n"
            "  - WORDPRESS_APP_PASSWORD"
        )
    
    # 创建 WordPress 客户端
    print("="*60)
    print("🚀 开始发布 Markdown 到 WordPress")
    print("="*60)
    print(f"📄 输入文件: {markdown_file}")
    print(f"📊 文章状态: {status}")
    print(f"🖼️  图片处理: {'跳过' if skip_images else ('试运行' if dry_run else '上传')}")
    print()
    
    client = WordPressClient(
        wordpress_url=wordpress_url,
        username=wordpress_username,
        app_password=wordpress_password,
        disable_proxy=False
    )
    
    # 创建临时目录用于存放中间文件
    temp_dir = Path(tempfile.mkdtemp(prefix='wp_publish_'))
    if keep_temp_files:
        print(f"📁 临时文件目录: {temp_dir}")
    
    result = {
        'success': False,
        'post_id': None,
        'post_link': None,
        'images': {
            'total': 0,
            'uploaded': 0,
            'failed': 0,
            'skipped': 0
        },
        'invalid_images': [],
        'failed_images': [],
        'temp_files': []
    }
    
    try:
        # 步骤 1: 上传图片到 WordPress（如果未跳过）
        markdown_with_images = markdown_file
        if not skip_images:
            print("\n" + "="*60)
            print("📸 步骤 1/3: 上传图片到 WordPress")
            print("="*60)
            
            # 检查是否有图片
            with open(markdown_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            image_links = extract_image_links(content)
            
            if image_links:
                # 创建临时文件用于保存更新后的 Markdown
                temp_md_file = temp_dir / f"{markdown_path.stem}_with_images.md"
                
                image_result = upload_images_and_update_markdown(
                    markdown_file=markdown_file,
                    output_file=str(temp_md_file),
                    wp_client=client,
                    dry_run=dry_run
                )
                
                result['images'] = {
                    'total': image_result['total_images'],
                    'uploaded': image_result['uploaded'],
                    'failed': image_result['failed'],
                    'skipped': image_result['skipped']
                }
                invalid_links = image_result.get('skipped_invalid', [])
                result['invalid_images'] = invalid_links
                if invalid_links:
                    print("\n⚠️ 下列图片因为非 http(s) 或预检失败被跳过：")
                    for url, reason in invalid_links:
                        print(f"  - {url} ({reason})")
                
                failed_details = image_result.get('failed_details', [])
                result['failed_images'] = failed_details
                if failed_details and not dry_run:
                    print("\n⚠️ 以下图片上传失败（继续执行后续流程）：")
                    for url, reason in failed_details:
                        print(f"  - {url}\n    原因: {reason}")
                    print("\n提示：可稍后手动补传或使用 --skip-images 跳过图片上传。")
                
                if not dry_run:
                    markdown_with_images = str(temp_md_file)
                    try:
                        shutil.copy2(temp_md_file, markdown_path)
                        print("📝 已将更新后的 Markdown 覆盖写回原文件，后续步骤将使用新的图片链接")
                        result['updated_markdown_file'] = str(markdown_path)
                    except Exception as copy_exc:
                        print(f"⚠️ 覆盖原 Markdown 文件失败: {copy_exc}")
                    result['temp_files'].append(str(temp_md_file))
                    print(f"✅ 图片处理完成，更新后的 Markdown 已保存")
                else:
                    print("🔍 试运行完成，未实际上传图片")
                    markdown_with_images = markdown_file  # 试运行模式下使用原文件
            else:
                print("⚠️  未在 Markdown 中找到图片链接，跳过图片上传步骤")
        else:
            print("\n" + "="*60)
            print("⏭️  步骤 1/3: 跳过图片上传")
            print("="*60)
        
        # 步骤 2: 将 Markdown 转换为 HTML
        print("\n" + "="*60)
        print("🔄 步骤 2/3: 将 Markdown 转换为 HTML")
        print("="*60)
        
        temp_html_file = temp_dir / f"{markdown_path.stem}.html"
        
        print(f"正在转换: {markdown_with_images} -> {temp_html_file}")
        convert_markdown_to_html(
            md_file_path=markdown_with_images,
            output_file_path=str(temp_html_file),
            inline_styles=True
        )
        
        result['temp_files'].append(str(temp_html_file))
        print(f"✅ HTML 转换完成: {temp_html_file}")
        
        # 步骤 3: 上传 HTML 到 WordPress
        print("\n" + "="*60)
        print("📤 步骤 3/3: 上传到 WordPress")
        print("="*60)
        
        if dry_run:
            print("🔍 试运行模式：跳过实际上传")
            print(f"📄 将上传的文件: {temp_html_file}")
        else:
            post = upload_html_to_wordpress(
                html_file_path=str(temp_html_file),
                status=status
            )
            
            if post:
                result['success'] = True
                result['post_id'] = post['id']
                result['post_link'] = post.get('link')
                
                print("\n" + "="*60)
                print("🎉 发布成功！")
                print("="*60)
                print(f"📝 文章 ID: {post['id']}")
                print(f"📌 文章标题: {post['title']['rendered']}")
                print(f"📊 文章状态: {post['status']}")
                if result['post_link']:
                    print(f"🔗 文章链接: {result['post_link']}")
            else:
                print("\n❌ 上传失败")
                return result
        
        # 打印统计信息
        if not skip_images and result['images']['total'] > 0:
            print("\n" + "="*60)
            print("📊 图片处理统计")
            print("="*60)
            print(f"总图片数: {result['images']['total']}")
            print(f"✅ 成功上传: {result['images']['uploaded']}")
            print(f"❌ 上传失败: {result['images']['failed']}")
            print(f"⏭️  跳过: {result['images']['skipped']}")
            if result['invalid_images']:
                print(f"⚠️ 无效/预检失败: {len(result['invalid_images'])}")
            if result['failed_images']:
                print("\n⚠️ 失败的图片列表：")
                for url, reason in result['failed_images']:
                    print(f"  - {url}\n    原因: {reason}")
                print()
        
        return result
        
    except Exception as e:
        print(f"\n❌ 发生错误: {str(e)}")
        import traceback
        traceback.print_exc()
        result['error'] = str(e)
        return result
        
    finally:
        # 清理临时文件（除非指定保留）
        if not keep_temp_files and temp_dir.exists():
            try:
                shutil.rmtree(temp_dir)
                print(f"\n🧹 已清理临时文件")
            except Exception as e:
                print(f"\n⚠️  清理临时文件时出错: {e}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='将 Markdown 文件发布到 WordPress 的完整流程',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基本用法（保存为草稿）
  python scripts/publish_markdown_to_wordpress.py examples/test222_zh.md

  # 直接发布
  python scripts/publish_markdown_to_wordpress.py examples/test222_zh.md --status publish

  # 跳过图片上传（如果图片已经上传过）
  python scripts/publish_markdown_to_wordpress.py examples/test222_zh.md --skip-images

  # 试运行模式（仅显示将要处理的图片，不实际上传）
  python scripts/publish_markdown_to_wordpress.py examples/test222_zh.md --dry-run

  # 保留临时文件（用于调试）
  python scripts/publish_markdown_to_wordpress.py examples/test222_zh.md --keep-temp
        """
    )
    
    parser.add_argument(
        'markdown_file',
        type=str,
        help='输入的 Markdown 文件路径'
    )
    
    parser.add_argument(
        '--status',
        choices=['draft', 'publish', 'pending', 'private'],
        default='draft',
        help='文章状态（默认: draft）'
    )
    
    parser.add_argument(
        '--skip-images',
        action='store_true',
        help='跳过图片上传步骤（如果图片已经上传过）'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='试运行模式（仅显示将要处理的图片，不实际上传）'
    )
    
    parser.add_argument(
        '--keep-temp',
        action='store_true',
        help='保留临时文件（用于调试）'
    )
    
    args = parser.parse_args()
    
    # 检查文件是否存在
    if not Path(args.markdown_file).exists():
        print(f"❌ 错误: 文件 {args.markdown_file} 不存在")
        sys.exit(1)
    
    # 执行发布流程
    result = publish_markdown_to_wordpress(
        markdown_file=args.markdown_file,
        status=args.status,
        skip_images=args.skip_images,
        dry_run=args.dry_run,
        keep_temp_files=args.keep_temp
    )
    
    # 根据结果退出
    if result.get('success') or args.dry_run:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()

