import Queue
import threading
import codecs
import datetime
import os
import whoosh
from whoosh.analysis import StandardAnalyzer, SimpleAnalyzer
from whoosh.searching import Searcher
from whoosh.index import exists_in, create_in, open_dir
from whoosh.fields import Schema, STORED, ID, KEYWORD, TEXT


#from . import searchfiles, indexfiles, indexutils, addmetadata
from . import searchfiles, indexutils, indexfiles, indexCSV

class Corpus:
    scoreDocs = None
    allTerms = None
    allDicts = None
    allMetadata = None
    termsDocs = None
    content_field = None
    # save the args_dir for rebuilding the index
    args_dir_c = None

    def __init__(self, path, analyzer_str = None, field_dict = None, content_field = None):
        self.path = path
        self.field_dict = {} if field_dict is None else field_dict
        if analyzer_str is None: analyzer_str = "StandardAnalyzer"
        self.content_field = "contents" if content_field is None else content_field.lower()
        self.analyzer_str = analyzer_str
        self.analyzer = self.get_analyzer_from_str(analyzer_str)


    def get_analyzer_from_str(self, analyzer_str):
        if analyzer_str == 'StandardAnalyzer':
            return StandardAnalyzer

class Worker(threading.Thread):
    def __init__(self, parent, corpus, action, args_dir = None):
        # This is a subclass of threading.Thread that makes sure all the processor-intensive Lucene functions take place
        # in a separate thread. To use it, pass Worker a reference to the main txtorgui instance (it will communicate back
        # to this instance using parent.write()) a Corpus class, and an "action" dictionary that tells the threading.Thread.run()
        # method what action to take. For example, action = {'search': 'query'} would run the lucene query 'query' and action =
        # {'export_tdm': 'outfile.csv'} would export a TDM to outfile.csv

        self.parent = parent
        self.corpus = corpus
        self.action = action
        self.args_dir = args_dir
        self._init_index()
        self.call = {}

        # Make the thread
        super(Worker,self).__init__()

    def run(self):

        # Start the thread
        #super(Worker,self).start()
        #super(Worker,self).join()                
        # yeah, this should be refactored
        if "search" in self.action.keys():
            self.run_searcher(self.action['search'])
        if "delete" in self.action.keys():
            self.delete_index(self.action['delete'])
        if "export_tdm" in self.action.keys():
            self.export_TDM(self.action['export_tdm'])
        if "export_tdm_csv" in self.action.keys():
            self.export_TDM_csv(self.action['export_tdm_csv'])
        if "export_tdm_stm" in self.action.keys():
            self.export_TDM_stm(self.action['export_tdm_stm'])
        if "export_contents" in self.action.keys():
            self.export_contents(self.action['export_contents'])
        if "import_directory" in self.action.keys():
            self.import_directory(self.action['import_directory'])
            self.call={'import_directory':self.action['import_directory']}
        if "import_csv" in self.action.keys():
            self.import_csv(self.action['import_csv'])
            self.call={'import_csv':self.action['import_csv']}            
        if "import_csv_with_content" in self.action.keys():
            self.import_csv_with_content(*self.action['import_csv_with_content'])
            self.call={'import_csv_with_content':self.action['import_csv_with_content']}
        if "rebuild_metadata_cache" in self.action.keys():
            self.rebuild_metadata_cache(*self.action['rebuild_metadata_cache'])
        if "reindex" in self.action.keys():
            self.reindex()


    def _init_index(self):

        if not os.path.exists(self.corpus.path):
            os.mkdir(self.corpus.path)

        analyzer = self.corpus.analyzer
        self.analyzer = self.corpus.analyzer
        
        if exists_in(self.corpus.path):
            ix = open_dir(self.corpus.path)
        else:
            # may need to remove this?  how can we have a schema if we don't know the...uh...schema?
            schema = Schema(title=TEXT(stored=True,analyzer=analyzer), content=TEXT(analyzer=analyzer),
                            path=ID(stored=True))
            ix = create_in(self.corpus.path,schema)
            writer = ix.writer()            
            writer.commit()

        self.index = ix
        self.searcher = ix.searcher();
        #self.reader = IndexReader.open(self.lucene_index, True)
        self.reader = ix.reader();
        #self.analyzer = self.corpus.analyzer

    def import_directory(self, dirname):
        res = indexfiles.IndexFiles(dirname, self.corpus.path, self.analyzer, self.args_dir)
        self.index = res.index
        

    def import_csv(self, csv_file):
        try:
            res = indexCSV.IndexCSV(self.corpus.path, self.analyzer, csv_file, None, self.args_dir)            
        except UnicodeDecodeError:
            self.parent.write({'error': 'CSV import failed: file contained non-unicode characters. Please save the file with UTF-8 encoding and try again!'})
            return
        self.parent.write({'message': "CSV import complete: {} rows added.".format(res.changed_rows)})

    def import_csv_with_content(self, csv_file, content_field):
        try:
            res = indexCSV.IndexCSV(self.corpus.path, self.analyzer, csv_file, content_field, self.args_dir)
        except UnicodeDecodeError:
            self.parent.write({'error': 'CSV import failed: file contained non-unicode characters. Please save the file with UTF-8 encoding and try again!'})
            return
        self.parent.write({'message': "CSV import complete: {} rows added.".format(res.changed_rows)})
        

    def reindex(self):
        # remove the old index
        # self._init_index()

        # # create the new index, just like before
        # args_dir = self.corpus.args_dir_c
        # print 'args_dir', args_dir
        # if 'dir' in args_dir:
        #     self.import_directory(args_dir['dir'])
        # elif 'file' in args_dir:
        #     self.import_csv(args_dir['file'])
        # elif 'full_file' in args_dir:
        #     self.import_csv_with_content(args_dir['file'],self.corpus.content_field)
            
        
        # self.parent.write({'message': "Reindex successful. Corpus analyzer is now set to %s." % (self.corpus.analyzer_str,)})
        self.parent.write({'status': "Ready!"})

    def delete_index(self, cache_filename):
        indexutils.delete_index(self.corpus.path)
        self.rebuild_metadata_cache(cache_filename, self.corpus.path, delete=True)
        self.parent.write({'message': "Delete successful. Corpus at %s has been removed from txtorg and from disk." % (self.corpus.path,)})
        self.parent.write({'status': "Ready!"})

    def run_searcher(self, command):
        start_time = datetime.datetime.now()
        try:
            self.parent.write({'status': 'Running whoosh query %s' % (command,)})
            #scoreDocs, allTerms, allDicts, termsDocs = searchfiles.run(self.searcher, self.analyzer, self.reader, command, self.corpus.content_field)
            scoreDocs, allTerms, allDicts, termsDocs, allMetadata = searchfiles.run(self.index, self.searcher, self.analyzer, self.reader, command, self.corpus.content_field)

        except Exception as e:
            self.parent.write({'error': str(e)})
            raise e

        end_time = datetime.datetime.now()
        self.parent.write({'query_results': (scoreDocs, allTerms, allDicts, termsDocs, allMetadata)})
        self.parent.write({'status': 'Query completed in %s seconds' % ((end_time - start_time).microseconds*.000001)})

    def export_TDM(self, outfile):
        if self.corpus.scoreDocs is None or self.corpus.allTerms is None or self.corpus.allDicts is None:
            self.parent.write({'error': "No documents selected, please run a query before exporting a TDM."})
            return

        searchfiles.write_CTM_TDM(self.corpus.scoreDocs, self.corpus.allDicts, self.corpus.allTerms,
                                  self.corpus.termsDocs,self.searcher,self.reader, self.corpus.allMetadata,
                                  outfile,False,self.corpus.minVal,self.corpus.maxVal)
        self.parent.write({'message': "TDM exported successfully!"})

    def export_TDM_csv(self, outfile):
        if self.corpus.scoreDocs is None or self.corpus.allTerms is None or self.corpus.allDicts is None:
            self.parent.write({'error': "No documents selected, please run a query before exporting a TDM."})
            return

        searchfiles.writeTDM(self.corpus.allDicts, self.corpus.allTerms, self.corpus.termsDocs, outfile, self.corpus.minVal,self.corpus.maxVal)
        self.parent.write({'message': "TDM exported successfully!"})

    def export_TDM_stm(self, outfile):
        if self.corpus.scoreDocs is None or self.corpus.allTerms is None or self.corpus.allDicts is None:
            self.parent.write({'error': "No documents selected, please run a query before exporting a TDM."})
            return
        searchfiles.write_CTM_TDM(self.corpus.scoreDocs, self.corpus.allDicts, self.corpus.allTerms,
                                  self.corpus.termsDocs,self.searcher,self.reader, self.corpus.allMetadata,outfile,
                                  True,self.corpus.minVal,self.corpus.maxVal)
        self.parent.write({'message': "TDM exported successfully!"})

    def export_contents(self, outfile):
        if self.corpus.scoreDocs is None or self.corpus.allTerms is None or self.corpus.allDicts is None:
            self.parent.write({'error': "No documents selected, please run a query before exporting document contents."})
            return

        failed = searchfiles.write_contents(self.corpus.allDicts, self.searcher, self.reader, outfile, content_field = self.corpus.content_field)
        if not failed:
            self.parent.write({'message': "Document contents exported successfully!"})
        else:
            self.parent.write({'error': "Some documents could not be exported. Please check to make sure no files have moved on disk."})


    def rebuild_metadata_cache(self, cache_filename, corpus_directory, delete = False):
        metadata_dict = indexutils.get_fields_and_values(self.reader)
        # finds the section of the old file to overwrite, and stores the old file in memory.
        # if delete is True, it will remove the index from the file
        old_file = []
        start = -1
        stop = -1
        idx = 0
        with codecs.open(cache_filename, 'r', encoding='UTF-8') as inf:
            for idx, line in enumerate(inf):
                if "CORPUS:" in line and line.strip().endswith(corpus_directory):
                    start = idx
                elif "CORPUS:" in line and start != -1 and stop == -1:
                    stop = idx
                old_file.append(line)
            if stop == -1: stop = idx+1

        if not delete:
            new_segment = ["CORPUS: " + corpus_directory + '\n', "_ANALYZER: " + self.corpus.analyzer_str +'\n', "_CONTENTFIELD: " + self.corpus.content_field + '\n']
            for k in metadata_dict.keys():
                metadata_dict[k] = metadata_dict[k]
                # sanitize various characters from input.
                new_segment.append(k + ": [" + "|".join(metadata_dict[k]).replace('\n','').replace(']','').replace('[','').replace(':','') + "]\n")
        else:
            new_segment = []

        if start == -1:
            new_file = old_file + new_segment
        else:
            new_file = old_file[:start] + new_segment + old_file[stop:]

        with codecs.open(cache_filename, 'w', encoding='UTF-8') as outf:
            for line in new_file:
                outf.write(line)
        with codecs.open(cache_filename, 'r', encoding='UTF-8') as outf:
            mystr = outf.read()
        self.parent.write({'rebuild_cache_complete': None})
        self.parent.write({'message': 'Finished rebuilding cache file.'})
