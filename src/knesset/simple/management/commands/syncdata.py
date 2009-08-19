 # This Python file uses the following encoding: utf-8
import os
from django.core.management.base import NoArgsCommand
from optparse import make_option
from django.conf import settings

import urllib2
import re
import gzip

import datetime

from knesset.simple.models import *
from django.db import connection
from django.db.models import Max

DATA_ROOT = getattr(settings, 'DATA_ROOT',
                    os.path.join(settings.PROJECT_ROOT, 'data'))


class Command(NoArgsCommand):
    option_list = NoArgsCommand.option_list + (
        make_option('--no-download', action='store_true', dest='no-download',
            help="don't download data. only load the data from the files in knesset/data/ to the db."),
        make_option('--no-process', action='store_true', dest='no-process',
            help="download data and save it to files in knesset/data/ only. don't load the data to the db."),
        make_option('--no-correlations', action='store_true', dest='no-correlations',
            help="don't calculate correlations after loading the data (mainly for debug)."),

    )
    help = "Downloads data from sources, parses it and loads it to the Django DB."

    requires_model_validation = False

    last_id = 1

    def Download(self):
        f = gzip.open(os.path.join(DATA_ROOT, 'results.tsv.gz'), "ab")
        f = gzip.open(os.path.join(DATA_ROOT, 'votes.tsv.gz'),"ab")
        r = range(self.last_id,13000) # this is the range of page ids to go over. currently its set manually.
        for id in r:
            page = self.ReadPage(id)
            title = self.PageTitle(page)
            if(title == """הצבעות במליאה-חיפוש"""): # found no vote with this id
                print "no vote found at id %d" % id
            else:
                countFor = 0
                countAgainst = 0
                countAbstain = 0
                countNoVote = 0
                (name,date) = self.VoteData(page)
                results = self.ReadMemberVotes(page)
                for i in results:
                    f.write("%d\t%s\t%s\t%s\t%s\t%s\n" % (id,name,date,i[0],i[1],i[2]))
                    if(i[2]=="for"):
                        countFor+=1
                    if(i[2]=="against"):
                        countAgainst+=1
                    if(i[2]=="abstain"):
                        countAbstain+=1
                    if(i[2]=="no-vote"):
                        countNoVote+=1
                f2.write("%d\t%s\t%s\t%d\t%d\t%d\t%d\n" % (id, name, date, countFor,countAgainst,countAbstain,countNoVote))
                print "parsed data at id %d" % id
            print " %.2f%% done" % ( (100.0*(float(id)-r[0]))/(r[-1]-r[0]) )
        f.close()
        f2.close()


    def UpdateLastDownloadedId(self):
        """
        Reads local votes file, and sets self.last_downloaded_id to the highest id found in the file.
        This is later used to skip downloading of data alreay downloaded.
        """
        f = gzip.open(os.path.join(DATA_ROOT, 'votes.tsv.gz'))
        content = f.read().split('\n')
        for line in content:
            if(len(line)<2):
                continue
            s = line.split('\t')
            vote_id = int(s[0])
            if vote_id > self.last_id:
                self.last_id = vote_id
        print "last id found in local files is %d. will try to download more." % self.last_id
        f.close()

    hebMonths = ['ינואר','פברואר','מרץ','אפריל','מאי','יוני','יולי','אוגוסט','ספטמבר','אוקטובר','נובמבר','דצמבר']


    # some party names appear in the knesset website in several forms.
    # this dictionary is used to transform them to canonical form.
    partyAliases = {'עבודה':'העבודה',
                    'ליכוד':'הליכוד',
                    'ש"ס-התאחדות ספרדים שומרי תורה':'ש"ס',
                    'יחד (ישראל חברתית דמוקרטית) והבחירה הדמוקרטית':'יחד (ישראל חברתית דמוקרטית) והבחירה הדמוקרטית',
                    'בל"ד-ברית לאומית דמוקרטית':'בל"ד',
                    'אחריות לאומית':'קדימה',
                    'יחד (ישראל חברתית דמוקרטית) והבחירה הדמוקרטית':'מרצ-יחד והבחירה הדמוקרטית',
                    'יחד והבחירה הדמוקרטית':'מרצ-יחד והבחירה הדמוקרטית',
                    'יחד והבחירה הדמוקרטית (מרצ לשעבר)':'מרצ-יחד והבחירה הדמוקרטית',
                    'יחד (ישראל חברתית דמוקרטית) והבחירה הדמוקרטית':'מרצ-יחד והבחירה הדמוקרטית',
                    'יחד  (ישראל חברתית דמוקרטית) והבחירה הדמוקרטית':'מרצ-יחד והבחירה הדמוקרטית',
                    }


    def UpdateDbFromFiles(self):
        print "Update DB From Files"

        try:
            f = gzip.open(os.path.join(DATA_ROOT, 'results.tsv.gz'))
            content = f.read().split('\n')
            parties = dict() # key: party-name; value: Party
            members = dict() # key: member-name; value: Member
            votes   = dict() # key: id; value: Vote
            memberships = dict() # key: (member.id,party.id)
            current_vote = None # used to track what vote we are on, to create vote objects only for new votes
            current_max_src_id = Vote.objects.aggregate(Max('id'))['id__max']
            if current_max_src_id == None: # the db contains no votes, meanins its empty
                current_max_src_id = 0
            print "%s processing data" % str(datetime.datetime.now())
            for line in content:
                if(len(line)<2):
                    continue
                s = line.split('\t')
                
                vote_id = s[0]
                if vote_id < current_max_src_id: # skip votes already parsed.
                    continue                
                vote_label = s[1]
                relevant = False

                # some votes are intersting, some are just stupid. so lets load only something that has potential to be interesting
                if(vote_label.find('אישור החוק') >= 0):
                    relevant = True
                #if(vote_label.find('קריאה שניה') >= 0):
                #    relevant = True
                #if(vote_label.find('הצבעה') >= 0):
                #    relevant = True

                if not relevant:
                    continue

                vote_time_string = s[2].replace('&nbsp;',' ')
                for i in self.hebMonths:
                    if i in vote_time_string:
                        month = self.hebMonths.index(i)+1
                day = re.search("""(\d\d?)""", vote_time_string).group(1)
                year = re.search("""(\d\d\d\d)""", vote_time_string).group(1)
                vote_date = datetime.date(int(year),int(month),int(day))
                voter = s[3]
                voter_party = s[4]

                # transform party names to canonical form
                if(voter_party in self.partyAliases):
                    voter_party = self.partyAliases[voter_party]

                vote = s[5]

                # create/get the party appearing in this vote 
                if voter_party in parties:
                    p = parties[voter_party]
                    created = False
                else:
                    p,created = Party.objects.get_or_create(name=voter_party)
                #if created: # this is magic needed because of unicode chars. if you don't do this, the object p will have gibrish as its name. 
                            #only when it comes back from the db it has valid unicode chars.
                #    p = Party.objects.get(name=voter_party) 
                
                # use this vote's time to update the party's start date and end date
                if (p.start_date is None) or (p.start_date > vote_date):
                    p.start_date = vote_date
                if (p.end_date is None) or (p.end_date < vote_date):
                    p.end_date = vote_date
                if created:
                    p.save() # save on first time, so it would have an id, be able to link, etc.
                
                # create/get the member voting
                if voter in members:
                    m = members[voter]
                    created = False
                else:
                    m,created = Member.objects.get_or_create(name=voter)
                m.party = p;
                #if created: # again, unicode magic
                #    m = Member.objects.get(name=voter)
                # use this vote's date to update the member's dates.
                if (m.start_date is None) or (m.start_date > vote_date):
                    m.start_date = vote_date
                if (m.end_date is None) or (m.end_date < vote_date):
                    m.end_date = vote_date
                if created:
                    m.save()
        
                    
                # create/get the membership (connection between member and party)
                if ((m.id,p.id) in memberships):
                    ms = memberships[(m.id,p.id)]                
                    created = False
                else:
                    ms,created = Membership.objects.get_or_create(member=m,party=p)
                #if created: # again, unicode magic
                #    ms = Membership.objects.get(member=m,party=p)
                # again, update the dates on the membership
                if (ms.start_date is None) or (ms.start_date > vote_date):
                    ms.start_date = vote_date
                if (ms.end_date is None) or (ms.end_date < vote_date):
                    ms.end_date = vote_date
                if created:
                    ms.save()    
                    
                # create/get a vote object for this vote
                if (current_vote == None) or (vote_id != current_vote.src_id): # we are parsing a new vote. need to create new object
                    if vote_id in votes:
                        v = votes[vote_id]
                        created = False
                    else:                
                        v,created = Vote.objects.get_or_create(title=vote_label, time_string=vote_time_string, importance=1)
                    if created: # again, unicode magic
                 #       v = Vote.objects.get(title=vote_label, time_string=vote_time_string)
                        v.time = vote_date
                        v.src_id = vote_id
                        
                        votes[vote_id] = v
                    current_vote = v
                # and add the current member's vote
                if vote=='for':
                    current_vote.voted_for.add(m)
                if vote=='against':
                    current_vote.voted_against.add(m)
                if vote=='abstain':
                    current_vote.voted_abstain.add(m)
                if vote=='no-vote':
                    current_vote.didnt_vote.add(m)
                if created:
                    current_vote.save()
                
            print "%s done" % str(datetime.datetime.now())
            print "%s saving data " % str(datetime.datetime.now())
            for p in parties:
                p.save()
            for m in members:
                m.save()
            for ms in memberships:
                ms.save()
            for v in votes:
                v.save()
            print "%s done" % str(datetime.datetime.now())
        except Exception,e:
            print "error: %s" % e
            
    def CalculateCorrelations(self):
        print "Calculate Correlations"
        try:     
            cursor = connection.cursor()
            print "%s truncate correlations table" % str(datetime.datetime.now())
            Correlation.objects.all().delete()
            print "%s calculate correlations"  % str(datetime.datetime.now())
            cursor.execute("""insert into simple_correlation (m1_id,m2_id,score) (
                select m1 as m1_id, m2 as m2_id,sum(score) as score from (
                select a1.member_id as m1,a2.member_id as m2, count(*) as score from (
                (select * from simple_vote_voted_for) a1,
                (select * from simple_vote_voted_for) a2
                ) where a1.vote_id = a2.vote_id and a1.member_id < a2.member_id group by a1.member_id,a2.member_id
                union
                select a1.member_id as m1,a2.member_id as m2, count(*) as score from (
                (select * from simple_vote_voted_against) a1,
                (select * from simple_vote_voted_against) a2
                ) where a1.vote_id = a2.vote_id and a1.member_id < a2.member_id group by a1.member_id,a2.member_id
                union
                select a1.member_id as m1,a2.member_id as m2, -count(*) as score from (
                (select * from simple_vote_voted_for) a1,
                (select * from simple_vote_voted_against) a2
                ) where a1.vote_id = a2.vote_id and a1.member_id < a2.member_id group by a1.member_id,a2.member_id
                union
                select a1.member_id as m1,a2.member_id as m2, -count(*) as score from (
                (select * from simple_vote_voted_against) a1,
                (select * from simple_vote_voted_for) a2
                ) where a1.vote_id = a2.vote_id and a1.member_id < a2.member_id group by a1.member_id,a2.member_id
                
                ) a group by m1,m2
                )""".replace('\n',''))
            print "%s done"  % str(datetime.datetime.now())
            print "%s normalizing correlation"  % str(datetime.datetime.now())
            cursor.execute("""update simple_correlation,
                (select member_id,sum(vote_count) as vote_count from (
                select member_id,count(*) as vote_count from simple_vote_voted_for group by member_id
                union
                select member_id,count(*) as vote_count from simple_vote_voted_against group by member_id
                ) a 
                group by member_id) a1,
                (select member_id,sum(vote_count) as vote_count from (
                select member_id,count(*) as vote_count from simple_vote_voted_for group by member_id
                union
                select member_id,count(*) as vote_count from simple_vote_voted_against group by member_id
                ) a 
                group by member_id) a2
                set simple_correlation.normalized_score = simple_correlation.score / sqrt(a1.vote_count) / sqrt(a2.vote_count)*100 
                where simple_correlation.m1_id = a1.member_id and simple_correlation.m2_id = a2.member_id""")

        except Exception,e:
            print "error: %s" % e
     

    def ReadPage(self,voteId):
        url = "http://www.knesset.gov.il/vote/heb/Vote_Res_Map.asp?vote_id_t=%d" % voteId
        urlData = urllib2.urlopen(url)
        page = urlData.read().decode('windows-1255').encode('utf-8')
        return page

    def ReadMemberVotes(self,page):
        results = []
        pattern = re.compile("""Vote_Bord""")
        match = pattern.split(page)
        for i in match:
            vote = ""
            if(re.match("""_R1""", i)):
                vote = "for"
            if(re.match("""_R2""", i)):
                vote = "against"
            if(re.match("""_R3""", i)):
                vote = "abstain"
            if(re.match("""_R4""", i)):
                vote = "no-vote"
            if(vote != ""):
                name = re.search("""DataText4>([^<]*)</a>""",i).group(1);
                name = re.sub("""&nbsp;""", " ", name)
                party = re.search("""DataText4>([^<]*)</td>""",i).group(1);
                party = re.sub("""&nbsp;""", " ", party)
                if(party == """ " """):
                    party = lastParty
                else:
                    lastParty = party 
                results.append((name, party, vote))  
        return results


    def PageTitle(self,page):
        title = re.search("""<TITLE>([^<]*)</TITLE>""", page)
        return title.group(1)

    def VoteData(self,page):
        name = re.search("""שם החוק: </td>[^<]*<[^>]*>([^<]*)<""", page).group(1)
        name = name.replace("\t"," ")
        name = name.replace("\n"," ")
        name = name.replace("\r"," ")
        name = name.replace("&nbsp;"," ")
        date = re.search("""תאריך: </td>[^<]*<[^>]*>([^<]*)<""",page)
        return (name, date.group(1))


    def handle_noargs(self, **options):


        no_download = options.get('no-download', False)
        no_process = options.get('no-process', False)
        no_correlations = options.get('no-correlations', False)

        if not no_download:
            self.UpdateLastDownloadedId()
            self.Download()    
        
        if not no_process:
            self.UpdateDbFromFiles()

        if not no_correlations:
            self.CalculateCorrelations()


        