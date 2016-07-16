angular.module('aiddataDET')
.controller('QueryTextCtrl', function($scope, $rootScope, $stateParams, queryFactory) {
  $scope.filters = queryFactory.filters;
  $scope.dataset = {};
  $scope.totals = {};
  $scope.geography = $stateParams.boundary;

  $rootScope.$on('filters:update', function(e, data) {
    $scope.searchData = data;
  });

  $rootScope.$on('filters:updated', function(e, data) {
    $scope.totals = _.pick(data, ['projects', 'locations']);

    // Being Redefined with each filters:updated event because it directly
    // references $scope vars which will need to be update
    $scope.queryStructure = [
      { value: [ $scope.dataset.title ], pre: 'Extract data from ', optional: false },
      { value: [ $scope.geography ], pre: 'within ', optional: false },
      { value: $scope.searchData.donors, pre: 'given by ', optional: true, key: 'donors' },
      { value: $scope.searchData.ad_sector_names, pre: 'to promote ', optional: true, key: 'ad_sector_names' }
    ];
  });

  $rootScope.$on('dataset:selected', function(e, data) {
    $scope.dataset = data;
  });

  $scope.removeFilter = function(filter, option) {
    queryFactory.toggleFilterOff(filter, option);
  };

  function init () {
    queryFactory.setBoundary($stateParams.boundary, $stateParams.subboundary);
  }
  init();
});
