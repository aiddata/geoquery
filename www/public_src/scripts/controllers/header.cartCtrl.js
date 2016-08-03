angular.module('aiddataDET')
.controller('CartCtrl', function($scope, $rootScope, $log, $stateParams, $state, queryFactory, ajaxFactory) {
  $scope.queryObj = {};

  $rootScope.$on('query:updated', function(event, data) {
    $scope.queryObj = data;
  });

  $scope.datasetDetails = function (q) {
    var datasetName = q.dataset || q.name;
    return queryFactory.getDataset(datasetName);
  };

  $scope.removeQuery = function (q, type) {
    queryFactory.removeRequest(q, type)
      .then(function(query) {
        $rootScope.$broadcast('query:updated', query);
      });
  };

  $scope.submitQuery = function () {
    // var email = 'eslivinski@gmail.com';
    $state.go('checkout');
    // queryFactory.submitRequest(email)
    //   .then(function(data) {
    //     console.log('It Worked', data);
    //   }, function (err) {
    //     console.error('It didnt work', data);
    //   });
  };

});
