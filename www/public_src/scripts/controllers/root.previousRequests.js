angular.module('aiddataDET')
.controller('PreviousRequestsCtrl', function($scope, $rootScope, $log, $stateParams, $state, ajaxFactory, queryFactory) {

  $scope.requestForm = {
    email: ''
  };
  $scope.requests = [];

  $scope.lookup = function() {
    ajaxFactory.requests('email', $scope.requestForm.email)
      .then(function(results) {
        $scope.requests = results.data;
      }, function(err) {
        console.error(err);
      });
  };

  $scope.viewStatus = function (id) {
    var url = $state.href('status', { 'id': id });
    window.open(url, '_blank');
  };

  $scope.getStage = function(req) {
    return _.chain(req)
    .get('stage')
    .filter('time')
    .each(function(stage) {
      var timeUTC = new Date(stage.time * 1000);
      stage.timeFormat = queryFactory.getTimeStamp(timeUTC);
    })
    .last()
    .value();
  };

  $scope.logout = function() {
    $scope.requestForm.email = '';
    $scope.requests.splice(0);
  };

});
