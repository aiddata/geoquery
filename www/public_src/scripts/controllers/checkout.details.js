angular.module('aiddataDET')
.controller('DetailsCtrl', function($scope, $rootScope, $log, $q, $timeout, $state, $cookies, $element, $mdDialog, queryFactory, modalFactory, mapFactory, spinFactory, info, modals) {
  $scope.queryObj = queryFactory.getQuery();
  $scope.terms = [];
  $scope.queryData = {
    email: $cookies.get('email') || '',
    custom_name: 'Request ' + d3.timeFormat('%m-%d-%y %H:%M')(Date.now())
  };

  $scope.datasetDetails = function (q) {
    var datasetName = q.dataset || q.name;
    return queryFactory.getDataset(datasetName);
  };

  $scope.submitQuery = function () {
    spinFactory.start();

    queryFactory.submitRequest($scope.queryData)
      .then(function(data) {
        return $state.go('requests', { notify: true, email: $scope.queryData.email });
      }, function (err) {
        $log.error(err);
        return $state.go('requests', { email: $scope.queryData.email });
      })
      .finally(function() {
        $rootScope.$broadcast('query:updated');
        spinFactory.stop();
      });
  };

  $scope.$on('$viewContentLoaded', function() {
    $scope.terms = _.get(info, 'terms_and_conditions.content') || [];
    $scope.citation = _.get(info, 'citation') || '';

    mapFactory.provision(document.querySelector('.map'), true)
      .promise.then(function(){
        $scope.boundary = queryFactory.getSubBoundary();
        mapFactory.mapBoundary($scope.boundary.name);
      });

  });

});
