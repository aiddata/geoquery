# accepts request object and creates pdf documentation

import time
from pathlib import Path
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image, Table, TableStyle, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
import shapely
import pandas as pd

from gqcore.utils.db.conn import get_conn
from gqcore import get_config

# =============================================================================

styles = getSampleStyleSheet()

def pg(text, pg_type):
    """return paragraph of specified type for given text
    """
    text = str(text)
    if pg_type == 1:
        para = Paragraph(text, styles['Normal'])
        return para
    elif pg_type == 2:
        para = Paragraph(text, styles['BodyText'])
        return para
    else:
        raise Exception("invalid paragraph type")


def enforce_max_word_length(string, max_chars=80):
    raw_word_list = string.split(" ")
    short_word_list = []
    for word in raw_word_list:
        if len(word) > max_chars:
            split_word = [
                word[i:i+max_chars]
                for i in range(0, len(word), max_chars)
            ]
            fixed_word = "\n".join(split_word)
        else:
            fixed_word = word
        short_word_list += [fixed_word]
    return " ".join(short_word_list)


def get_request(request_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT * FROM requests WHERE id::text = %s""", (request_id,))
            request = cur.fetchone()
            return request

# TODO: this needs to be updated to reflect how meta attributes are used
def get_dataset_meta(dataset_name):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT * FROM datasets WHERE name = %s""", (dataset_name,))
            dataset = cur.fetchone()

            if dataset is None:
                return None, None

            cur.execute("""SELECT * FROM dataset_resources WHERE dataset_id = %s""", (dataset['id'],))
            dataset_resources = cur.fetchall()
            return dataset, dataset_resources


def get_dummy_request():
    import pandas as pd
    with get_conn() as conn:
        with conn.cursor() as cur:
            id_query = """
            SELECT *
            FROM (
                SELECT
                    requests.id as request_id,
                    sum(CASE WHEN (extract_tasks.status = 1) THEN 1 ELSE 0 END) AS completed,
                    count(extract_tasks.status) AS total
                FROM requests
                JOIN request_map
                    ON requests.id = request_map.req_id
                JOIN extract_tasks
                    ON request_map.task_id = extract_tasks.id
                WHERE requests.id::text = 'cae5aa10-eeb9-41a3-9395-f8226983092a'
                GROUP BY requests.id
            )
            JOIN requests ON request_id = requests.id
            JOIN request_map ON requests.id = request_map.req_id
            JOIN extract_tasks ON request_map.task_id = extract_tasks.id
            WHERE completed = total
            ORDER BY requests.priority DESC, requests.submit_time ASC
            LIMIT 1
            """
            cur.execute(id_query)
            result = cur.fetchone()
            if not result:
                return None, None, None
            request_id = result["request_id"]
            request_contact = result["contact"]
            data_query = """
                SELECT
                    extract_tasks.fm_id as fm_id,
                    extract_tasks.resource_id as resource_id,
                    extract_tasks.po_id as po_id,
                    extract_data.name as data_name,
                    extract_data.data_column as data_column,
                    extract_data.int_value as int_value,
                    extract_data.str_value as str_value,
                    extract_data.float_value as float_value,
                    feat_map.name as name,
                    feat_map.attr as attr,
                    features.shape as geom,
                    features.id as geom_id,
                    dataset_resources.name as resource_name,
                    dataset_resources.label as resource_label,
                    datasets.name as dataset_name,
                    processing_options.short_name as po_name,
                    processing_options.description as po_description,
                    processing_options.result_type as po_result_type
                FROM (
                    SELECT * FROM request_map
                    WHERE req_id = %s
                )
                AS request_map
                LEFT OUTER JOIN extract_tasks
                    ON task_id = extract_tasks.id
                LEFT OUTER JOIN extract_data
                    ON task_id = extract_data.id
                LEFT OUTER JOIN feat_map
                    ON extract_tasks.fm_id = feat_map.id
                LEFT OUTER JOIN features
                    ON feat_map.geom_id = features.id
                LEFT OUTER JOIN dataset_resources
                    ON extract_tasks.resource_id = dataset_resources.id
                LEFT OUTER JOIN datasets
                    ON dataset_resources.dataset_id = datasets.id
                LEFT OUTER JOIN processing_options
                    ON extract_tasks.po_id = processing_options.id
            """
            cur.execute(data_query, (request_id,))
            request_info = cur.fetchall()
            request_df = pd.DataFrame(request_info)
            return request_id, request_contact, request_df


class DocBuilder():

    def __init__(self, request_id, request_df, output_path):

        self.config = get_config()

        self.assets_dir = Path(self.config["main"]["data_root"]) / "src/gqcore/assets"

        request_id, request_contact, request_df = get_dummy_request()


        self.request_id = str(request_id)
        self.request_df = request_df
        self.output_path = str(output_path)

        self.download_server = self.config["other"]["request_url"]

        self.request = get_request(self.request_id)

        self.doc = 0

        # container for the 'Flowable' objects
        self.Story = []

        self.styles = getSampleStyleSheet()
        self.styles.add(ParagraphStyle(name='Justify', alignment=TA_JUSTIFY))
        self.styles.add(ParagraphStyle(name='Center', alignment=TA_CENTER))


    def time_str(self, timestamp=None):
        if isinstance(timestamp, datetime):
            return str(timestamp)

        elif timestamp != None:
            try:
                timestamp = int(timestamp)
                if timestamp == 0:
                    return "---"
            except:
                return "---"

        return time.strftime('%Y-%m-%d %H:%M:%S (%Z)', time.localtime(timestamp))


    def build_doc(self):

        rid = self.request_id
        # print('build_doc: ' + rid)

        self.doc = SimpleDocTemplate(self.output_path, pagesize=letter)

        # build doc call all functions

        self.add_header()
        self.Story.append(Spacer(1, 0.5*inch))
        self.add_info()
        self.Story.append(Spacer(1, 0.3*inch))
        self.add_timeline()
        self.Story.append(Spacer(1, 0.3*inch))
        self.add_cite_and_contents()
        self.Story.append(PageBreak())

        self.add_meta()
        self.Story.append(PageBreak())

        self.add_notes()
        self.Story.append(PageBreak())

        self.add_additional()

        self.output_doc()

        return True


    # write the document to disk
    def output_doc(self):
        self.doc.build(self.Story)


    # documentation header
    def add_header(self):
        # # aiddata logo
        # logo = self.assets_dir / 'templates/aid_data.png'

        # im = Image(logo, 2.188*inch, 0.5*inch)
        # im.hAlign = 'LEFT'
        # self.Story.append(im)

        # self.Story.append(Spacer(1, 0.25*inch))

        # title
        ptext = '<font size=20>AidData GeoQuery Request Documentation</font>'
        self.Story.append(Paragraph(ptext, self.styles['Center']))


    # report generation info
    def add_info(self):
        ptext = '<b><font size=14>Report Info</font></b>'
        self.Story.append(Paragraph(ptext, self.styles['BodyText']))
        self.Story.append(Spacer(1, 0.1*inch))

        data = [
            ['Request Name', self.request['custom_name'].encode('utf8', 'replace')],
            ['Request Id', str(self.request_id)],
            ['Email', self.request['contact']],
            ['Generated on', self.time_str()],
            ['Download Link', '<a href="http://{0}/query/#!/status/{1}">{0}/query/#!/status/{1}</a>'.format(
                self.download_server, self.request_id)]
        ]

        data = [[i[0], pg(i[1], 1)] for i in data]
        t = Table(data)

        t.setStyle(TableStyle([
            ('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
            ('BOX', (0,0), (-1,-1), 0.25, colors.black)
        ]))

        self.Story.append(t)


    # full request timeline / other processing info
    def add_timeline(self):

        ptext = '<b><font size=14>Processing Timeline</font></b>'
        self.Story.append(Paragraph(ptext, self.styles['Normal']))
        self.Story.append(Spacer(1, 0.1*inch))

        data = [
            ["submit_time", self.time_str(self.request['submit_time'])],
            ["prepare_time", self.time_str(self.request['prepare_time'])],
            ["process_time", self.time_str(self.request['process_time'])],
            ["complete_time", self.time_str(int(time.time()))]
        ]

        data = [[i[0], pg(i[1], 1)] for i in data]
        t = Table(data)

        t.setStyle(TableStyle([
            ('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
            ('BOX', (0,0), (-1,-1), 0.25, colors.black)
        ]))

        self.Story.append(t)


    def add_cite_and_contents(self):

        with open(self.assets_dir / 'templates/general.txt') as general:
            for line in general:
                p = Paragraph(line, self.styles['BodyText'])
                self.Story.append(p)


    # intro paragraphs
    def add_notes(self):

        with open(self.assets_dir / 'templates/field_names.txt') as field_names:
            for line in field_names:
                p = Paragraph(line, self.styles['BodyText'])
                self.Story.append(p)

        self.Story.append(PageBreak())

        with open(self.assets_dir / 'templates/notes.txt') as field_names:
            for line in field_names:
                p = Paragraph(line, self.styles['BodyText'])
                self.Story.append(p)

        self.Story.append(PageBreak())

        with open(self.assets_dir / 'templates/aid_data.txt') as field_names:
            for line in field_names:
                p = Paragraph(line, self.styles['BodyText'])
                self.Story.append(p)


    # license stuff
    def add_additional(self):

        with open(self.assets_dir / 'templates/additional.txt') as license:
            for line in license:
                p = Paragraph(line, self.styles['BodyText'])
                self.Story.append(p)


# =============================================================================
# =============================================================================
# =============================================================================
# =============================================================================
# =============================================================================


    def add_meta(self):


        ptext = '<b><font size=14>Feature Meta Information</font></b>'
        self.Story.append(Paragraph(ptext, self.styles['Normal']))
        self.Story.append(Spacer(1, 0.25*inch))


        fdata = self.build_fc_meta()


        for ix, (fc_data, display_name) in enumerate(fdata):

            ptext = '<font size=10><b>Feature Collection {0} - {1}</b></font>'.format(
                ix, display_name)
            self.Story.append(Paragraph(ptext, self.styles['Normal']))
            self.Story.append(Spacer(1, 0.05*inch))

            fc_data = [[i[0], pg(i[1], 2)] for i in fc_data]
            t = Table(fc_data)
            t.setStyle(TableStyle([
                ('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
                ('BOX', (0,0), (-1,-1), 0.25, colors.black)
            ]))

            self.Story.append(KeepTogether(t))
            self.Story.append(Spacer(1, 0.1*inch))



        ptext = '<b><font size=14>Dataset Meta Information</font></b>'
        self.Story.append(Paragraph(ptext, self.styles['Normal']))
        self.Story.append(Spacer(1, 0.25*inch))

        datasets = self.request_df["dataset_name"].unique()

        self.dataset_meta_log = []

        for ix, d in enumerate(datasets):

            # build dataset meta table array
            data, display_name = self.build_dataset_meta(d)

              # if d['name'] not in dataset_meta_log:
            self.dataset_meta_log.append(d)

            ptext = '<font size=10><b>Selection {0} - {1}</b></font>'.format(
                len(self.dataset_meta_log), display_name)
            self.Story.append(Paragraph(ptext, self.styles['Normal']))
            self.Story.append(Spacer(1, 0.05*inch))

            data = [[i[0], pg(i[1], 2)] for i in data]
            t = Table(data)
            t.setStyle(TableStyle([
                ('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
                ('BOX', (0,0), (-1,-1), 0.25, colors.black)
            ]))

            self.Story.append(KeepTogether(t))
            self.Story.append(Spacer(1, 0.1*inch))



    def build_fc_meta(self):

        feature_maps = self.request_df["fm_id"].unique()

        fm_query = """
        SELECT
            feat_map.id as fm_id,
            feat_map.name as name,
            feat_map.attr as attr,
            feat_map.geom_id as geom_id,
            fc.id as fc_id,
            fc.name as fc_name
        FROM feat_map
        JOIN feature_collections as fc
            ON feat_map.fc_id = fc.id
        WHERE feat_map.id IN ({0})
        """.format(",".join([str(i) for i in feature_maps]))

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(fm_query)
                fm_results = cur.fetchall()

        fm_results = pd.DataFrame(fm_results)


        fc_query = """
        SELECT *
        FROM feature_collections
        WHERE id IN ({0})
        """.format(",".join([str(i) for i in fm_results["fc_id"].unique()]))

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(fc_query)
                fc_results = cur.fetchall()

        fc_results = pd.DataFrame(fc_results)

        data = []
        for ix, fc in fc_results.iterrows():

            fc_data = [
                ['Title', fc["title"]],
                ['Name', fc["name"]],
                ['Description', fc["description"]],
                ['Source', fc["source_name"]],
                ['Source URL', fc["source_url"]],
                ['Citation', fc["citation"]],
                ['Bounding Box', shapely.wkb.loads(fc["spatial_extent"]).wkt],
                ['Feature Count', fm_results.loc[fm_results["fc_id"] == fc["id"]].shape[0]],
                ['Feature Names', ", ".join(fm_results.loc[fm_results["fc_id"] == fc["id"]]["name"])],
                ['Feature IDs', ", ".join(fm_results.loc[fm_results["fc_id"] == fc["id"]]["geom_id"].astype(str))],
            ]
            data.append((fc_data, fc["title"]))


        return data


    def build_dataset_meta(self, dataset_name):

        # get metadata for dataset
        dataset_meta, dataset_resources = get_dataset_meta(dataset_name)

        if dataset_meta is None:
            msg = f'Could not lookup dataset ({dataset_name}) for build_dataset_meta'
            raise Exception(msg)

        # build generic dataset_meta
        data = [
            ['Title', dataset_meta['title']],
            ['Name', dataset_name],
        ]

        request_dataset_df = self.request_df.loc[self.request_df['dataset_name'] == dataset_name]
        request_fields = ['dataset_name', 'resource_label', 'data_name']
        data_cols = request_dataset_df[request_fields].sort_values(by=request_fields).apply(lambda x: '.'.join(x), axis=1).unique()

        colnames_list =  data_cols

        colnames = ('Format: "{0}.&lt;temporal&gt;.&lt;method&gt;" <br /> '
                    'for all combinations of &lt;temporal&gt; and &lt;method&gt; '
                    'which can be found in the "Temporal Selection" and '
                    '"Extract Types Selected" fields below '
                    '({1} columns total)').format(
                        dataset_name, len(colnames_list)
                    )

        data.append(['Column Names ', colnames])

        temporal_raw = request_dataset_df["resource_label"].unique()

        if any([i in temporal_raw for i in ['none', None]]):
            temporal_str = temporal_raw
        else:
            temporal_int = [int(s) for s in temporal_raw]
            temporal_sorted = sorted(temporal_int, reverse=True)
            temporal_str = [str(ts) for ts in temporal_sorted]

        max_temporal_str_len = 25

        temporal_str_sub = temporal_str
        if len(temporal_str) > max_temporal_str_len:
            temporal_str_sub = temporal_str[:max_temporal_str_len]

        temporal_text = ', '.join(temporal_str_sub)
        if len(temporal_str) > max_temporal_str_len:
            temporal_text += ', ...'
        data.append(['Temporal Selection (' + str(len(temporal_str)) + ')', temporal_text])

        # prevent issue due to missing extract_types_info field

        unique_po = request_dataset_df.groupby(['po_name']).agg('first').reset_index()
        data.append(['Extract Types Selected', ', '.join([
            "{0} [{1}] - {2}".format(i["po_name"], i["po_result_type"], i["po_description"])
            for _, i in unique_po.iterrows()
        ])])

        data.append(['',''])
        data.append(['Description', dataset_meta['description']])

        details = "(no additional details)"
        if "details" in dataset_meta:
            details = dataset_meta["details"]
        data.append(['Details', details])

        data.append(['Bounding Box', shapely.wkb.loads(dataset_meta['spatial_extent']).wkt])

        data.append(['Date Added', str(dataset_meta['date_added'])])
        data.append(['Date Updated', str(dataset_meta['date_updated'])])

        if 'sources_name' in dataset_meta and dataset_meta['sources_name']:
            data.append(['Source Name', dataset_meta['sources_name']])

        if 'sources_web' in dataset_meta and dataset_meta['sources_web']:
            data.append(['Source URL', enforce_max_word_length(dataset_meta['source_url'])])

        if 'citation' in dataset_meta and dataset_meta['citation']:
            data.append(['Citation', enforce_max_word_length(dataset_meta['citation'])])

        if 'variable_description' in dataset_meta and dataset_meta['variable_description']:
            data.append(['Variable Description', dataset_meta['variable_description']])
        if 'resolution' in dataset_meta and dataset_meta['resolution']:
            data.append(['Resolution', str(dataset_meta['resolution'])])
        if 'factor' in dataset_meta and dataset_meta['factor']:
            data.append(['Factor', str(dataset_meta['factor'])])

        return data, dataset_meta['title']
