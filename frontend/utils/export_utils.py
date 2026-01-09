import io
import traceback

def df_to_csv_bytes(df):
    try:
        return df.to_csv(index=False).encode('utf-8')
    except Exception:
        return None


def figs_to_pdf_bytes(figs, title="Charts Report", status_text=None, metrics=None, guidance=None, ai_recommendation=None, images=None):
    """
    Convert a list of plotly figures to a PDF report (bytes).
    Wrapper around dashboard_to_pdf_bytes for backwards compatibility.
    Requires `kaleido` (for plotly.io.to_image) and `reportlab` to be installed.
    Returns PDF bytes, or raises ImportError with instructions if libraries missing.
    """
    dashboard_data = {
        'status_text': status_text or '',
        'metrics': metrics or {},
        'guidance': guidance or '',
        'figs': figs if isinstance(figs, list) else [figs],
        'ai_recommendation': ai_recommendation or '',
        'images': images or [],
    }
    return dashboard_to_pdf_bytes(dashboard_data, title=title)


def dashboard_to_pdf_bytes(dashboard_data, title="Dashboard Report"):
    """
    Convert dashboard data to a comprehensive PDF report (bytes).
    Includes text summaries, metrics, and charts.
    Requires `kaleido` (for plotly.io.to_image) and `reportlab` to be installed.
    Returns PDF bytes, or raises ImportError with instructions if libraries missing.
    """
    try:
        import plotly.io as pio
        # Ensure kaleido is available and configured
        pio.kaleido.scope.default_format = "png"
        pio.kaleido.scope.default_width = 500
        pio.kaleido.scope.default_height = 400
    except Exception as e:
        raise ImportError("plotly.io.to_image requires the 'kaleido' package. Install with: pip install kaleido")

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
        from reportlab.lib.utils import ImageReader
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle
        from reportlab.lib.units import inch
    except Exception:
        raise ImportError("PDF generation requires the 'reportlab' package. Install with: pip install reportlab")

    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        story = []

        # Title - split into main title and subtitle
        if '(Generated on' in title:
            # Split title into main title and generation time
            main_title = title.split(' (Generated on')[0]
            subtitle = '(Generated on' + title.split('(Generated on')[1]
            
            title_style = styles['Heading1']
            story.append(Paragraph(main_title, title_style))
            
            subtitle_style = styles['Normal']
            story.append(Paragraph(subtitle, subtitle_style))
        else:
            # Fallback to original single-line title
            title_style = styles['Heading1']
            story.append(Paragraph(title, title_style))
        
        story.append(Spacer(1, 12))

        def _process_ai_section(section_lines):
            """Helper function to process a section of AI recommendation text."""
            if not section_lines:
                return
            
            # Join lines that belong together
            combined_text = ' '.join(section_lines)
            
            # Check if this is a bullet point section
            if any(line.startswith('• ') or '**' in line for line in section_lines):
                # Process each line separately for bullet points
                for line in section_lines:
                    line = line.strip()
                    if not line:
                        continue
                    
                    if line.startswith('• ') or line.startswith('- ') or line.startswith('* '):
                        # Bullet point - handle bold formatting
                        bullet_content = line[2:].strip() if line.startswith(('• ', '- ', '* ')) else line
                        
                        # Handle bold text within bullet points
                        if '**' in bullet_content:
                            # Split by bold markers and format
                            parts = bullet_content.split('**')
                            formatted_parts = []
                            for i, part in enumerate(parts):
                                if i % 2 == 1:  # Odd indices are bold
                                    formatted_parts.append(f'<b>{part}</b>')
                                else:
                                    formatted_parts.append(part)
                            formatted_text = ''.join(formatted_parts)
                        else:
                            formatted_text = bullet_content
                        
                        story.append(Paragraph(f"• {formatted_text}", styles['Normal']))
                        story.append(Spacer(1, 6))  # Add spacing after bullet points
                    else:
                        # Regular line in bullet section
                        story.append(Paragraph(line, styles['Normal']))
                        story.append(Spacer(1, 6))  # Add spacing after regular lines
            else:
                # Regular paragraph section
                story.append(Paragraph(combined_text, styles['Normal']))
                story.append(Spacer(1, 6))  # Add spacing after paragraphs

        # Status Summary
        if dashboard_data.get('status_text'):
            status_style = styles['Heading2']
            story.append(Paragraph("Current Status", status_style))
            story.append(Paragraph(dashboard_data['status_text'], styles['Normal']))
            story.append(Spacer(1, 12))

        # Metrics
        if dashboard_data.get('metrics'):
            metrics_style = styles['Heading2']
            story.append(Paragraph("Key Metrics", metrics_style))
            for metric_name, metric_value in dashboard_data['metrics'].items():
                story.append(Paragraph(f"<b>{metric_name}:</b> {metric_value}", styles['Normal']))
            story.append(Spacer(1, 12))

        # Summary Statistics
        if dashboard_data.get('summary_stats'):
            stats_style = styles['Heading2']
            story.append(Paragraph("Summary Statistics", stats_style))
            stats = dashboard_data.get('summary_stats')
            if isinstance(stats, dict):
                for k, v in stats.items():
                    story.append(Paragraph(f"<b>{k}:</b> {v}", styles['Normal']))
            else:
                story.append(Paragraph(str(stats), styles['Normal']))
            story.append(Spacer(1, 12))

        # Filters
        if dashboard_data.get('filters'):
            filters_style = styles['Heading2']
            story.append(Paragraph("Filters", filters_style))
            filt = dashboard_data.get('filters')
            if isinstance(filt, dict):
                for k, v in filt.items():
                    story.append(Paragraph(f"<b>{k}:</b> {v}", styles['Normal']))
            else:
                story.append(Paragraph(str(filt), styles['Normal']))
            story.append(Spacer(1, 12))

        # Charts
        if dashboard_data.get('figs'):
            charts_style = styles['Heading2']
            story.append(Paragraph("Charts & Analysis", charts_style))
            story.append(Spacer(1, 12))

            for fig_item in dashboard_data['figs']:
                if isinstance(fig_item, dict):
                    fig = fig_item['fig']
                    title = fig_item.get('title', '')
                    if title:
                        story.append(Paragraph(title, styles['Heading3']))
                        story.append(Spacer(1, 6))
                else:
                    fig = fig_item
                
                try:
                    img_bytes = pio.to_image(fig, format='png', width=500, height=400, engine='kaleido')
                    img = RLImage(io.BytesIO(img_bytes), width=5*inch, height=4*inch)
                    story.append(img)
                    story.append(Spacer(1, 12))
                except Exception as e:
                    story.append(Paragraph(f"Chart could not be included: {str(e)}", styles['Normal']))
                    story.append(Spacer(1, 12))

        # Raw Images (for matplotlib figures, etc.)
        if dashboard_data.get('images'):
            for img_item in dashboard_data['images']:
                if isinstance(img_item, dict) and 'bytes' in img_item:
                    title = img_item.get('title', '')
                    img_bytes = img_item['bytes']
                    if title:
                        story.append(Paragraph(title, styles['Heading3']))
                        story.append(Spacer(1, 6))
                    
                    try:
                        img = RLImage(io.BytesIO(img_bytes), width=4*inch, height=3*inch)
                        story.append(img)
                        story.append(Spacer(1, 12))
                    except Exception as e:
                        story.append(Paragraph(f"Image could not be included: {str(e)}", styles['Normal']))
                        story.append(Spacer(1, 12))

        # Tables
        if dashboard_data.get('tables'):
            tables = dashboard_data.get('tables')
            for t in tables:
                if not isinstance(t, dict):
                    continue
                t_title = t.get('title')
                df = t.get('df')
                if df is None:
                    continue
                try:
                    rows = df.values.tolist()
                    headers = list(df.columns)
                except Exception:
                    continue

                if t_title:
                    story.append(Paragraph(str(t_title), styles['Heading2']))
                    story.append(Spacer(1, 6))

                # Convert all cells to wrapped Paragraphs
                body_style = styles['BodyText']
                table_data = [[Paragraph(str(h), body_style) for h in headers]]
                for r in rows:
                    table_data.append([Paragraph('' if v is None else str(v), body_style) for v in r])

                table = Table(table_data, repeatRows=1)
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                    ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 4),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                    ('TOPPADDING', (0, 0), (-1, -1), 2),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                ]))
                story.append(table)
                story.append(Spacer(1, 12))

        # Guidance
        if dashboard_data.get('guidance'):
            guidance_style = styles['Heading2']
            story.append(Paragraph("Guidance", guidance_style))
            story.append(Paragraph(dashboard_data['guidance'], styles['Normal']))
            story.append(Spacer(1, 12))

        # AI Recommendation
        if dashboard_data.get('ai_recommendation'):
            ai_style = styles['Heading2']
            story.append(Paragraph("AI Recommendation", ai_style))
            
            # Format the AI recommendation with proper structure and styling
            recommendation_text = dashboard_data['ai_recommendation']
            
            # Split into lines and process each section
            lines = recommendation_text.split('\n')
            current_section = []
            
            for line in lines:
                line = line.strip()
                if not line:
                    # Empty line - process current section if it exists
                    if current_section:
                        _process_ai_section(current_section)
                        current_section = []
                    continue
                
                # Check for section headers
                if line.startswith('## '):
                    # Process previous section first
                    if current_section:
                        _process_ai_section(current_section)
                        current_section = []
                    # Add the header as a subheading
                    header_text = line[3:].strip()
                    story.append(Paragraph(header_text, styles['Heading3']))
                elif line.startswith('Here are some suggestions') or line.startswith('It\'s important to remember'):
                    # Process previous section first
                    if current_section:
                        _process_ai_section(current_section)
                        current_section = []
                    # Add this as a regular paragraph
                    current_section.append(line)
                else:
                    current_section.append(line)
            
            # Process any remaining section
            if current_section:
                _process_ai_section(current_section)
            
            story.append(Spacer(1, 12))

        doc.build(story)
        buffer.seek(0)
        return buffer.read()
    except Exception as e:
        traceback.print_exc()
        raise
