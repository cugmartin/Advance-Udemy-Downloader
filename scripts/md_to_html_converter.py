"""
Markdown 转 HTML 转换器
将 Markdown 文件转换为带有精美样式的 HTML 文件
基于 test222.html 的样式特征
"""

import re
import sys
from pathlib import Path

try:
    import markdown
    from markdown.extensions import tables, fenced_code
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False
    print("警告: 未安装 markdown 库，将使用基础转换")
    print("建议运行: pip install markdown")

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    print("警告: 未安装 beautifulsoup4 库，无法转换为内联样式")
    print("建议运行: pip install beautifulsoup4")


def get_css_styles():
    """返回完整的 CSS 样式（从 test222.html 中提取）"""
    return """        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.8;
            color: #333;
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            padding: 20px;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: #ffffff;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.15);
            overflow: hidden;
        }

        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 60px 40px;
            text-align: center;
        }

        .header h1 {
            font-size: 2.5em;
            margin-bottom: 20px;
            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.2);
        }

        .content {
            padding: 40px;
        }

        img {
            max-width: 100%;
            height: auto;
            border-radius: 12px;
            margin: 8px 0;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
        }

        h2 {
            font-size: 32px !important;
            margin-top: 20px;
            margin-bottom: 4px;
            padding-bottom: 0;
            border-bottom: none;
        }

        h3 {
            font-size: 24px !important;
            margin-top: 20px;
            margin-bottom: 15px;
        }

        h4 {
            font-size: 20px !important;
            margin-top: 20px;
            margin-bottom: 10px;
        }

        p {
            margin: 0;
            padding: 8px 0;
            text-align: justify;
        }

        .h2-divider {
            display: block;
            width: 100%;
            height: 3px;
            margin-top: 16px;
            margin-bottom: 6px;
            border-radius: 999px;
            background: linear-gradient(90deg, #5c7cfa, #4fb3ff);
        }

        /* 表格样式 */
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 30px 0;
            background: #ffffff;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.08);
        }

        table strong {
            color: #000000;
            font-weight: 600;
        }

        thead {
            background: #333333;
            color: #ffffff;
        }

        th {
            padding: 15px;
            text-align: left;
            font-weight: 700;
            font-size: 1.05em;
            color: #ffffff;
            background: #333333;
        }

        th strong {
            color: #ffffff;
            font-weight: 700;
        }

        td {
            padding: 15px;
            border-bottom: 1px solid #eee;
            color: #000000;
            background: #ffffff;
        }

        td strong {
            color: #000000;
            font-weight: 600;
        }

        tbody tr {
            background-color: #ffffff;
        }

        /* 引用块样式 */
        blockquote {
            border-left: 5px solid #667eea;
            background: linear-gradient(90deg, #f0f4ff 0%, #ffffff 100%);
            padding: 20px 30px;
            margin: 25px 0;
            border-radius: 8px;
            font-style: italic;
            box-shadow: 0 3px 10px rgba(0, 0, 0, 0.05);
        }

        blockquote strong {
            color: #667eea;
            font-size: 1.1em;
        }

        /* 列表样式 */
        ul, ol {
            margin: 20px 0;
            padding-left: 30px;
        }

        li {
            margin: 10px 0;
            line-height: 1.8;
        }

        ul li::marker {
            color: #667eea;
        }

        /* 链接样式 */
        a {
            color: #667eea;
            text-decoration: none;
            transition: all 0.3s ease;
            border-bottom: 2px solid transparent;
        }

        a:hover {
            color: #764ba2;
            border-bottom-color: #764ba2;
        }

        /* 分隔线 */
        hr {
            border: none;
            height: 3px;
            background: linear-gradient(90deg, transparent, #667eea, transparent);
            margin: 40px 0;
        }

        /* 强调文本 */
        strong {
            color: #667eea;
            font-weight: 600;
        }

        /* 代码块（如果有） */
        code {
            background: #f4f4f4;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            color: #e83e8c;
        }

        /* 推荐框 */
        .recommendation {
            background: linear-gradient(135deg, #ffeaa7 0%, #fdcb6e 100%);
            padding: 25px;
            border-radius: 12px;
            margin: 30px 0;
            border-left: 5px solid #f39c12;
            box-shadow: 0 5px 15px rgba(243, 156, 18, 0.2);
        }

        /* FAQ 样式 */
        .faq-item {
            background: #f8f9fa;
            padding: 20px;
            margin: 15px 0;
            border-radius: 10px;
            border-left: 4px solid #667eea;
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }

        .faq-item:hover {
            transform: translateX(5px);
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.1);
        }

        .faq-question {
            font-weight: 600;
            color: #667eea;
            margin-bottom: 10px;
            font-size: 1.1em;
        }

        /* 作者信息 */
        .author-box {
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            color: white;
            padding: 30px;
            border-radius: 15px;
            margin: 40px 0;
            text-align: center;
        }

        .author-box img {
            border-radius: 50%;
            width: 100px;
            height: 100px;
            margin-bottom: 15px;
            border: 4px solid white;
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.2);
        }

        /* 响应式设计（保持标题字号不变，仅调整容器与表格） */
        @media (max-width: 768px) {
            .header h1 {
                font-size: 1.8em;
            }

            .content {
                padding: 20px;
            }

            table {
                font-size: 0.9em;
            }

            th, td {
                padding: 10px;
            }
        }

        /* 滚动动画 */
        @keyframes fadeIn {
            from {
                opacity: 0;
                transform: translateY(20px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        .content > * {
            animation: fadeIn 0.6s ease-out;
        }


        /* 按钮样式 */
        .cta-button {
            display: inline-block;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px 30px;
            border-radius: 50px;
            text-decoration: none;
            font-weight: 600;
            margin: 20px 0;
            transition: all 0.3s ease;
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }

        .cta-button:hover {
            transform: translateY(-3px);
            box-shadow: 0 8px 20px rgba(102, 126, 234, 0.6);
        }

        /* 徽章样式 */
        .badge {
            display: inline-block;
            background: #667eea;
            color: white;
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 0.85em;
            margin: 0 5px;
        }

        /* 高亮框 */
        .highlight-box {
            background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%);
            padding: 20px;
            border-radius: 10px;
            margin: 20px 0;
            border-left: 5px solid #4caf50;
        }
"""


def extract_title(markdown_text):
    """从 Markdown 文本中提取第一个 H1 标题"""
    lines = markdown_text.split('\n')
    for line in lines:
        line = line.strip()
        if line.startswith('# '):
            return line[2:].strip()
    return ""


def add_h2_dividers(html_content: str) -> str:
    """在每个 h2 后插入渐变分隔线"""
    pattern = re.compile(r'(<h2[^>]*>.*?</h2>)', re.DOTALL | re.IGNORECASE)

    def insert_divider(match: re.Match[str]) -> str:
        return (
            f'{match.group(1)}\n'
            '<span class="h2-divider" aria-hidden="true">&nbsp;</span>'
        )

    return pattern.sub(insert_divider, html_content)


def wrap_recommendation_blocks(html_content):
    """将包含 "Quick Recommendation" 或 "Recommended by" 的内容包装在 .recommendation div 中"""
    # 查找包含推荐文本的段落及其后续内容
    patterns = [
        (r'(<p><strong>💡\s*Quick Recommendation:</strong></p>)\s*(.*?)(?=<h|<hr|$)', 
         r'<div class="recommendation">\1\2</div>', re.DOTALL),
        (r'(<p>💡\s*<strong>Recommended by the author:</strong></p>)\s*(.*?)(?=<hr|$)', 
         r'<div class="recommendation">\1\2</div>', re.DOTALL),
    ]
    
    for pattern, replacement, flags in patterns:
        html_content = re.sub(pattern, replacement, html_content, flags=flags)
    
    return html_content


def wrap_faq_items(html_content):
    """将 FAQ 部分的问题和答案包装在 .faq-item div 中"""
    # 查找 "FAQs about" 标题后的内容（直到下一个h2或文件末尾）
    faq_pattern = r'(<h2[^>]*>.*?FAQs.*?</h2>.*?)(<p><strong>Frequently Asked Questions</strong>.*?</p>)?(.*?)(?=<h2|<hr|$)'
    
    def process_faq_section(match):
        header = match.group(1) if match.group(1) else ''
        faq_intro = match.group(2) if match.group(2) else ''
        faq_content = match.group(3) if match.group(3) else ''
        
        # 查找每个问题和答案对
        # 模式：**问题** 后面跟着答案段落（可能多行）
        faq_item_pattern = r'<p><strong>([^<]+\?)</strong></p>\s*(<p>[^<]+</p>(?:\s*<p>[^<]+</p>)*)'
        
        def wrap_faq(m):
            question = m.group(1).strip()
            answer = m.group(2)
            return f'<div class="faq-item">\n                <p class="faq-question">{question}</p>\n                {answer}\n            </div>'
        
        faq_content = re.sub(faq_item_pattern, wrap_faq, faq_content, flags=re.DOTALL)
        
        return header + faq_intro + faq_content
    
    html_content = re.sub(faq_pattern, process_faq_section, html_content, flags=re.DOTALL | re.IGNORECASE)
    
    return html_content


def wrap_highlight_boxes(html_content):
    """将 "Key to symbols" 等内容包装在 .highlight-box div 中"""
    patterns = [
        (r'(<p><strong>Key to symbols:</strong></p>)\s*(<ul>.*?</ul>)', 
         r'<div class="highlight-box">\1\2</div>', re.DOTALL),
    ]
    
    for pattern, replacement, flags in patterns:
        html_content = re.sub(pattern, replacement, html_content, flags=flags)
    
    return html_content


def add_ids_to_headings(html_content):
    """为标题添加 id 属性（基于标题文本生成）"""
    def generate_id(text):
        # 移除 HTML 标签和 emoji，转换为小写，替换空格为连字符
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'[^\w\s-]', '', text)
        text = text.lower().strip()
        text = re.sub(r'\s+', '-', text)
        return text
    
    def replace_heading(match):
        tag = match.group(1)
        content = match.group(2)
        heading_id = generate_id(content)
        return f'<{tag} id="{heading_id}">{content}</{tag}>'
    
    # 为 h2 和 h3 添加 id
    html_content = re.sub(r'<(h[23])>(.*?)</h[23]>', replace_heading, html_content)
    
    return html_content


def parse_css_to_dict(css_text):
    """将 CSS 文本解析为字典，便于应用内联样式"""
    css_dict = {}
    # 移除注释
    css_text = re.sub(r'/\*.*?\*/', '', css_text, flags=re.DOTALL)
    
    # 匹配 CSS 规则: selector { properties }
    pattern = r'([^{]+)\{([^}]+)\}'
    matches = re.finditer(pattern, css_text)
    
    for match in matches:
        selector = match.group(1).strip()
        properties = match.group(2).strip()
        
        # 跳过媒体查询、动画等
        if selector.startswith('@') or selector.startswith('*'):
            continue
        
        # 解析属性
        props_dict = {}
        for prop_match in re.finditer(r'([^:;]+):([^;]+);?', properties):
            key = prop_match.group(1).strip()
            value = prop_match.group(2).strip()
            props_dict[key] = value
        
        if props_dict:
            css_dict[selector] = props_dict
    
    return css_dict


def apply_inline_styles(html_content, keep_structure=True):
    """
    将 CSS 样式转换为内联样式，避免被 WordPress 过滤
    
    Args:
        html_content: HTML 内容（可以是完整文档或片段）
        keep_structure: 是否保留完整 HTML 结构（包括 head, body 等）
    
    Returns:
        转换后的 HTML 字符串
    """
    if not HAS_BS4:
        print("警告: beautifulsoup4 未安装，跳过内联样式转换")
        return html_content
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 提取样式
    style_tag = soup.find('style')
    if not style_tag:
        # 如果没有 style 标签，直接返回
        return str(soup) if keep_structure else str(soup.find('body') or soup.find('div', class_='content') or soup)
    
    css_text = style_tag.get_text()
    css_dict = parse_css_to_dict(css_text)
    
    # 移除 style 标签（因为 WordPress 会过滤）
    style_tag.decompose()
    
    # 应用内联样式到对应的元素
    for selector, styles in css_dict.items():
        selector = selector.strip()
        
        # 跳过通用选择器和特殊情况
        if selector.startswith('@') or selector.startswith('*'):
            continue
        
        # 移除伪类选择器（如 :hover, :nth-child 等）
        original_selector = selector
        selector = re.sub(r':[^:]+', '', selector)
        selector = selector.strip()
        
        if not selector:
            continue
        
        # 处理组合选择器（如 .author-box img, tbody tr）
        if ' ' in original_selector:
            parts = original_selector.split()
            parent_selector = parts[0].strip()
            child_selector = parts[-1].strip()
            
            # 移除伪类
            parent_selector = re.sub(r':[^:]+', '', parent_selector)
            child_selector = re.sub(r':[^:]+', '', child_selector)
            
            # 查找父元素
            parent_elements = []
            if parent_selector.startswith('.'):
                parent_class = parent_selector[1:]
                parent_elements = soup.find_all(class_=lambda x: x and parent_class in x.split())
            elif parent_selector.startswith('#'):
                parent_id = parent_selector[1:]
                parent_elem = soup.find(id=parent_id)
                if parent_elem:
                    parent_elements = [parent_elem]
            else:
                # 处理标签选择器（如 tbody）
                parent_tag = parent_selector.split()[0]
                parent_elements = soup.find_all(parent_tag)
            
            # 在父元素内查找子元素
            for parent in parent_elements:
                if child_selector.startswith('.'):
                    child_class = child_selector[1:]
                    child_elements = parent.find_all(class_=lambda x: x and child_class in x.split())
                elif child_selector.startswith('#'):
                    child_id = child_selector[1:]
                    child_elem = parent.find(id=child_id)
                    child_elements = [child_elem] if child_elem else []
                else:
                    child_tag = child_selector.split()[0]
                    child_elements = parent.find_all(child_tag)
                
                for elem in child_elements:
                    existing_style = elem.get('style', '')
                    new_styles = '; '.join([f"{k}: {v}" for k, v in styles.items()])
                    if existing_style and not existing_style.endswith(';'):
                        existing_style += '; '
                    elem['style'] = f"{existing_style}{new_styles}" if existing_style else new_styles
            
            continue  # 组合选择器已处理，跳过后续处理
        
        # 处理类选择器 .class
        if selector.startswith('.'):
            class_name = selector[1:].split()[0]  # 移除 . 并取类名
            elements = soup.find_all(class_=lambda x: x and class_name in x.split())
            for elem in elements:
                existing_style = elem.get('style', '')
                new_styles = '; '.join([f"{k}: {v}" for k, v in styles.items()])
                # 合并样式，避免重复
                if existing_style and not existing_style.endswith(';'):
                    existing_style += '; '
                elem['style'] = f"{existing_style}{new_styles}" if existing_style else new_styles
        
        # 处理 ID 选择器 #id
        elif selector.startswith('#'):
            id_name = selector[1:].split()[0]  # 移除 # 并取 ID
            elem = soup.find(id=id_name)
            if elem:
                existing_style = elem.get('style', '')
                new_styles = '; '.join([f"{k}: {v}" for k, v in styles.items()])
                # 合并样式，避免重复
                if existing_style and not existing_style.endswith(';'):
                    existing_style += '; '
                elem['style'] = f"{existing_style}{new_styles}" if existing_style else new_styles
        
        # 处理标签选择器 tag（如 body, h2, table 等）
        else:
            tag_name = selector.split()[0].split(':')[0].split('.')[0].split('#')[0]
            if tag_name and tag_name.isalnum():  # 确保是有效的标签名
                elements = soup.find_all(tag_name)
                for elem in elements:
                    existing_style = elem.get('style', '')
                    new_styles = '; '.join([f"{k}: {v}" for k, v in styles.items()])
                    # 合并样式，避免重复
                    if existing_style and not existing_style.endswith(';'):
                        existing_style += '; '
                    elem['style'] = f"{existing_style}{new_styles}" if existing_style else new_styles
    
    # 移除 script 标签（安全考虑，WordPress 可能也会过滤）
    for script in soup.find_all('script'):
        script.decompose()
    
    # 清理表格内样式，确保样式正确且无重复
    for table in soup.find_all('table'):
        # 处理表头（第一行）：确保所有文字都是白色
        for th in table.find_all('th'):
            # 设置 th 本身为白色文字
            th_style = th.get('style', '')
            if th_style:
                style_parts = [s.strip() for s in th_style.split(';') if s.strip()]
                style_dict = {}
                for part in style_parts:
                    if ':' in part:
                        key, value = part.split(':', 1)
                        key = key.strip()
                        value = value.strip()
                        style_dict[key] = value
                style_dict['color'] = '#ffffff'
                style_dict['background'] = '#333333'
                th['style'] = '; '.join([f"{k}: {v}" for k, v in style_dict.items()])
            
            # 确保 th 内的所有元素（包括 strong）都是白色
            for element in th.find_all(['strong', 'span', 'em', 'b', 'i']):
                elem_style = element.get('style', '')
                if elem_style:
                    style_parts = [s.strip() for s in elem_style.split(';') if s.strip()]
                    style_dict = {}
                    for part in style_parts:
                        if ':' in part:
                            key, value = part.split(':', 1)
                            key = key.strip()
                            value = value.strip()
                            style_dict[key] = value
                    style_dict['color'] = '#ffffff'
                    if element.name == 'strong':
                        style_dict['font-weight'] = '700'
                    element['style'] = '; '.join([f"{k}: {v}" for k, v in style_dict.items()])
                else:
                    # 如果没有样式，直接添加白色
                    if element.name == 'strong':
                        element['style'] = 'color: #ffffff; font-weight: 700'
                    else:
                        element['style'] = 'color: #ffffff'
        
        # 清理 tbody 内 strong 标签的样式，确保为黑色
        for strong in table.find_all('td'):
            for strong_elem in strong.find_all('strong'):
                style = strong_elem.get('style', '')
                if style:
                    # 解析样式，移除重复属性
                    style_parts = [s.strip() for s in style.split(';') if s.strip()]
                    style_dict = {}
                    for part in style_parts:
                        if ':' in part:
                            key, value = part.split(':', 1)
                            key = key.strip()
                            value = value.strip()
                            style_dict[key] = value
                    
                    # 确保 tbody 内的 strong 是黑色
                    style_dict['color'] = '#000000'
                    style_dict['font-weight'] = '600'
                    
                    # 重新组合样式
                    strong_elem['style'] = '; '.join([f"{k}: {v}" for k, v in style_dict.items()])
        
        # 清理 tbody tr 标签的重复背景色样式
        for tr in table.find_all('tr'):
            # 只处理 tbody 内的 tr
            if tr.parent and tr.parent.name == 'tbody':
                style = tr.get('style', '')
                if style:
                    style_parts = [s.strip() for s in style.split(';') if s.strip()]
                    style_dict = {}
                    for part in style_parts:
                        if ':' in part:
                            key, value = part.split(':', 1)
                            key = key.strip()
                            value = value.strip()
                            # 跳过 background-color，稍后统一设置
                            if key != 'background-color':
                                style_dict[key] = value
                    
                    # 统一设置为白色背景
                    style_dict['background-color'] = '#ffffff'
                    
                    # 重新组合样式
                    if style_dict:
                        tr['style'] = '; '.join([f"{k}: {v}" for k, v in style_dict.items()])
                    else:
                        tr['style'] = 'background-color: #ffffff'
    
    # 根据 keep_structure 参数决定返回内容
    if keep_structure:
        return str(soup)
    else:
        # 返回 content div 或 body（用于 WordPress 发布）
        content_div = soup.find('div', class_=re.compile(r'content', re.I))
        if content_div:
            return str(content_div)
        body = soup.find('body')
        if body:
            return str(body)
        return str(soup)


def convert_markdown_to_html(md_file_path, output_file_path=None, inline_styles=True):
    """
    将 Markdown 文件转换为 HTML 文件
    
    Args:
        md_file_path: Markdown 文件路径
        output_file_path: 输出 HTML 文件路径（如果为 None，则自动生成）
        inline_styles: 是否将 CSS 转换为内联样式（默认 True，避免被 WordPress 过滤）
    """
    # 读取 Markdown 文件
    md_path = Path(md_file_path)
    if not md_path.exists():
        raise FileNotFoundError(f"文件不存在: {md_file_path}")
    
    with open(md_path, 'r', encoding='utf-8') as f:
        md_content = f.read()
    
    # 提取标题
    title = extract_title(md_content)
    
    # 转换 Markdown 为 HTML
    if HAS_MARKDOWN:
        # 配置 Markdown 扩展
        md = markdown.Markdown(
            extensions=[
                'tables',
                'fenced_code',
                'nl2br',
            ]
        )
        html_body = md.convert(md_content)
    else:
        # 基础转换（简单实现）
        html_body = f"<pre>{md_content}</pre>"
        print("警告: 使用基础转换，建议安装 markdown 库以获得更好效果")
    
    # 后处理：添加 id、包装特殊元素
    html_body = add_ids_to_headings(html_body)
    html_body = wrap_recommendation_blocks(html_body)
    html_body = wrap_faq_items(html_body)
    html_body = wrap_highlight_boxes(html_body)
    html_body = add_h2_dividers(html_body)
    
    # 提取第一个 h1 标题和第一个图片
    h1_pattern = r'<h1[^>]*>(.*?)</h1>'
    h1_match = re.search(h1_pattern, html_body, re.DOTALL)
    
    header_html = ""
    if h1_match:
        # 提取纯文本标题（移除所有HTML标签、链接和特殊字符）
        title_text = h1_match.group(1)
        # 移除所有HTML标签（包括headerlink）
        title_text = re.sub(r'<[^>]+>', '', title_text)
        # 移除可能的HTML实体和特殊字符
        title_text = re.sub(r'&[^;]+;', '', title_text)
        title_text = title_text.strip()
        header_html = f'<div class="header">\n            <h1>{title_text}</h1>\n        </div>\n\n'
        # 从 body 中移除第一个 h1（保留在 header 中）
        html_body = re.sub(h1_pattern, '', html_body, count=1, flags=re.DOTALL)
    
    # 获取 CSS 样式
    css_styles = get_css_styles()
    
    # 构建完整的 HTML
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
{css_styles}
    </style>
</head>
<body>
    <div class="container">
        {header_html}
        <div class="content">
{html_body}
        </div>
    </div>
</body>
</html>
"""
    
    # 如果需要，将 CSS 转换为内联样式（避免被 WordPress 过滤）
    if inline_styles:
        print("正在将 CSS 转换为内联样式...")
        html_content = apply_inline_styles(html_content, keep_structure=True)
    
    # 确定输出文件路径
    if output_file_path is None:
        output_file_path = md_path.with_suffix('.html')
    
    # 写入 HTML 文件
    output_path = Path(output_file_path)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"✓ 转换完成: {md_file_path} -> {output_file_path}")
    if inline_styles:
        print("  ✓ CSS 已转换为内联样式，可直接用于 WordPress")
    return output_path


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='将 Markdown 文件转换为带有精美样式的 HTML 文件',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python md_to_html_converter.py test222.md
  python md_to_html_converter.py test222.md output.html
  python md_to_html_converter.py test222.md --no-inline
        """
    )
    parser.add_argument('markdown_file', help='输入的 Markdown 文件路径')
    parser.add_argument('output_file', nargs='?', default=None, 
                       help='输出的 HTML 文件路径（默认：自动生成）')
    parser.add_argument('--no-inline', action='store_true',
                       help='不转换为内联样式（保留 <style> 标签）')
    
    args = parser.parse_args()
    
    try:
        convert_markdown_to_html(
            args.markdown_file, 
            args.output_file,
            inline_styles=not args.no_inline
        )
    except Exception as e:
        print(f"✗ 错误: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()

