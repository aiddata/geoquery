angular.module('aiddataDET')
.controller('CartCtrl', function($scope, $rootScope, $log, $stateParams, $state, queryFactory) {
  $scope.queryObj = {};
  $scope.query = '{}';

  $rootScope.$on('query:updated', function(event, data) {
    $scope.queryObj = data;
    $scope.query = JSON.stringify(data, null, 4);
  });

  $scope.datasetDetails = function (q) {
    var datasetName = q.dataset || q.name;
    return queryFactory.getDataset(datasetName);
  };

});
