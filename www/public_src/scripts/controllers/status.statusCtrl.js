/**
  * This is the Controller for individual status pages
  */

angular.module('aiddataDET')
.controller('StatusCtrl', function($stateParams, $scope, $sce, request, datasets, info, queryFactory) {
  $scope.id = $stateParams.id;
  $scope.request = request;
  $scope.info = [];
  $scope.requestInfo = [];

  $scope.getDataset = function (query) {
    var name = query.dataset || query.name;

    return _.find(datasets, {name : name });
  };

  $scope.$on('$viewContentLoaded', function() {
    $scope.info = info.status;

    request.status = _.chain(request.stage)
      .filter('time')
      .each(function(stage) {
        stage.time_ms = stage.time * 1000;
        stage.time_format = queryFactory.getTimeStamp(stage.time_ms);
      })
      .last()
      .get('name')
      .value();

    request.submissionTime = _.get(_.head(request.stage), 'time_format') || '';
    $scope.requestInfo = _.map(request.info, function(p) {
      return $sce.trustAsHtml(p);
    });

  });

});
