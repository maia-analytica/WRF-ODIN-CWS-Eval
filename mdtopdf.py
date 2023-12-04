import markdown2
import pdfkit
from pdfkit.api import configuration

def convert_md_to_pdf(md_filepath, pdf_filepath):
    # Read the Markdown file
    with open(md_filepath, 'r') as file:
        md_content = file.read()

    # Convert Markdown to HTML
    html_content = markdown2.markdown(md_content)

    # Path to wkhtmltopdf executable
    # Update this path according to your actual wkhtmltopdf installation path
    path_wkthmltopdf = '/usr/local/bin/wkhtmltopdf' 
    config = pdfkit.configuration(wkhtmltopdf=path_wkthmltopdf)

    # Convert HTML to PDF and save
    pdfkit.from_string(html_content, pdf_filepath, configuration=config)

if __name__ == "__main__":
    # Convert 'cws_odin_overview.md' to 'cws_odin_overview.pdf'
    convert_md_to_pdf('cws_odin_overview.md', 'cws_odin_overview.pdf')