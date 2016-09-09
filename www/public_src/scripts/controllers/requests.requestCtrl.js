/**
  * This is the Controller for the requests page
  */

angular.module('aiddataDET')
.controller('RequestsCtrl', function($scope, $rootScope, $log, $q, $state, $stateParams, $timeout, queryFactory, requests) {

  $scope.email = $stateParams.email;

  $scope.$on('$viewContentLoaded', function(event) {
    $scope.requests = _.map(requests, function(req) {
      req.status = _.chain(req.stage)
        .filter('time')
        .each(function(stage) {
          stage.time_ms = stage.time * 1000;
          stage.time_format = queryFactory.getTimeStamp(stage.time_ms);
        })
        .last()
        .get('name')
        .value();

      req.statusDisplay = req.status.indexOf('submit') >= 0 ? 'submitted' :
        req.status.indexOf('complete') >= 0 ? 'completed' : 'processed';

      req.submissionTime = _.get(_.head(req.stage), 'time_format') || '';
      return req;
    });
  });
});
