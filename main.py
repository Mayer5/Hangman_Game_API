#!/usr/bin/env python

"""main.py - This file contains handlers that are called by task queue and/or
cronjobs."""

import webapp2
from google.appengine.api import mail, app_identity
from api import HangmanApi

from models import User


class SendReminderEmail(webapp2.RequestHandler):
    def get(self):
        """
        Send a reminder email to each User with an email about games.
        Called every hour using a cron job
        :return:
        """
        app_id = app_identity.get_application_id()
        users = User.query(User.email is not None)
        for user in users:
            games = Game.query(Game.user == user.key).filter(
                Game.game_over is False)
            if games.count() > 0:
                subject = 'This is a reminder!'
                body = 'Hello {}, you have unfinished games!'.format(user.name)
                # This will send test emails, the arguments to send_mail are:
                # from, to, subject, body
                mail.send_mail('noreply@{}.appspotmail.com'.format(app_id),
                               user.email, subject, body)


class UpdateAverageMovesRemaining(webapp2.RequestHandler):
    def post(self):
        """
        Update game listing announcement in memcache.
        :return:
        """
        HangmanApi._cache_average_attempts()
        self.response.set_status(204)


app = webapp2.WSGIApplication([
    ('/crons/send_reminder', SendReminderEmail),
    ('/tasks/cache_average_attempts', UpdateAverageMovesRemaining),
], debug=True)
